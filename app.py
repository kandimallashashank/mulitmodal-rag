from flask import Flask, render_template, request, jsonify,send_from_directory,current_app,send_file
from dotenv import load_dotenv
import os
import asyncio
from functools import wraps
import logging
import weaviate
from openai import AsyncOpenAI
from config import COLLECTION_NAME
import re

# Get the absolute path of the directory containing app.py
basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set up AsyncOpenAI client
openai_client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Initialize Weaviate client
client = None

# Global variable to track connection status
connection_status = {"status": "Disconnected", "color": "red"}

# Function to initialize the Weaviate client
async def initialize_weaviate_client(max_retries=3, retry_delay=5):
    global client, connection_status
    retries = 0
    while retries < max_retries:
        connection_status = {"status": "Connecting...", "color": "orange"}
        try:
            logger.info(f"Attempting to connect to Weaviate (Attempt {retries + 1}/{max_retries})")
            client = weaviate.Client(
                url=os.getenv('WCS_URL'),
                auth_client_secret=weaviate.auth.AuthApiKey(os.getenv('WCS_API_KEY')),
                additional_headers={
                    "X-OpenAI-Api-Key": os.getenv('OPENAI_API_KEY')
                }
            )
            # Test the connection
            await asyncio.to_thread(client.schema.get)
            connection_status = {"status": "Connected", "color": "green"}
            logger.info("Successfully connected to Weaviate")
            return connection_status
        except Exception as e:
            logger.error(f"Error connecting to Weaviate: {str(e)}")
            connection_status = {"status": f"Error: {str(e)}", "color": "red"}
            retries += 1
            if retries < max_retries:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Could not connect to Weaviate.")
    return connection_status

# Async-compatible caching decorator
def async_lru_cache(maxsize=1024):
    cache = {}

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = str(args) + str(kwargs)
            if key not in cache:
                if len(cache) >= maxsize:
                    cache.pop(next(iter(cache)))
                cache[key] = await func(*args, **kwargs)
            return cache[key]
        return wrapper
    return decorator

@async_lru_cache(maxsize=1000)
async def get_embedding(text):
    response = await openai_client.embeddings.create(
        input=text,
        model="text-embedding-3-large"
    )
    return response.data[0].embedding

async def search_multimodal(query: str, limit: int = 30, alpha: float = 0.6):
    logger.info(f"Starting multimodal search for query: {query}")
    try:
        query_vector = await get_embedding(query)
        logger.info(f"Generated query embedding of length {len(query_vector)}")
        
        response = await asyncio.to_thread(
            client.query.get(COLLECTION_NAME, ["content_type", "source_document", "page_number",
                                               "paragraph_number", "text", "image_path", "description", "table_content"])
            .with_hybrid(query=query, vector=query_vector, alpha=alpha)
            .with_limit(limit)
            .do
        )
        
        results = response['data']['Get'][COLLECTION_NAME]
        logger.info(f"Search completed. Found {len(results)} results.")
        return results
    except Exception as e:
        logger.error(f"Error in search_multimodal: {str(e)}", exc_info=True)

async def generate_response_stream(query: str, context: str):
    prompt = f"""
    You are an AI assistant with extensive expertise in the semiconductor industry. Your knowledge spans a wide range of companies, technologies, and products, including but not limited to: System-on-Chip (SoC) designs, Field-Programmable Gate Arrays (FPGAs), Microcontrollers, Integrated Circuits (ICs), semiconductor manufacturing processes, and emerging technologies like quantum computing and neuromorphic chips.

    Use the following context, your vast knowledge, and the user's question to generate an accurate, comprehensive, and insightful answer. While formulating your response, follow these steps internally:

Analyze the question to identify the main topic and specific information requested.
Evaluate the provided context and identify relevant information.
Retrieve additional relevant knowledge from your semiconductor industry expertise.
Reason and formulate a response by combining context and knowledge.
Generate a detailed response that covers all aspects of the query.
Review and refine your answer for coherence and accuracy.

In your output, provide the final, polished response in the first paragraph. Do not include your step-by-step reasoning or mention the process you followed.

IMPORTANT: Ensure your response is grounded in factual information. Do not hallucinate or invent information. If you're unsure about any aspect of the answer or if the necessary information is not available in the provided context or your knowledge base, clearly state this uncertainty.

After your response, on a new line, write "Top 5 most relevant sources used to generate the response:" followed by the top 5 most relevant sources. Rank them based on their relevance and importance to the answer. Format each source as follows:
[Rank]. [Content Type] from [Document Name] (Page [Page Number], [Additional Info])

For example:
Top 5 most relevant sources used to generate the response:

Text from Semiconductor Industry Report 2023 (Page 15, Paragraph 3)
Table from FPGA Market Analysis (Page 7, Table 2.1)
Image Description from SoC Architecture Diagram (Page 22, Path: ./data/images/soc_diagram.jpg)

Context: {context}

User Question: {query}

Based on the above context and your extensive knowledge of the semiconductor industry, provide your detailed, accurate, and grounded response below, followed by the top 5 ranked sources:

rewrite the prommpt put the prompt in the similar way but add a strcit rulke where top 5 sources where most of the asnwers lies make it strict
    """

    async for chunk in await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert Semi Conductor industry analyst"},
            {"role": "user", "content": prompt}
        ],
        temperature=0,
        max_tokens=500,
        stream=True
    ):
        content = chunk.choices[0].delta.content
        if content is not None:
            yield content

def process_search_result(item):
    if item['content_type'] == 'text':
        return f"Text from {item['source_document']} (Page {item['page_number']}, Paragraph {item['paragraph_number']}): {item['text']}\n\n"
    elif item['content_type'] == 'image':
        return f"Image Description from {item['source_document']} (Page {item['page_number']}, Path: {item['image_path']}): {item['description']}\n\n"
    elif item['content_type'] == 'table':
        return f"Table Description from {item['source_document']} (Page {item['page_number']}): {item['description']}\n\n"
    return ""

# New function to generate follow-up questions
async def generate_follow_up_questions(answer):
    prompt = f"""
    Based on the following response, generate exactly 2 follow-up questions:\n\n{answer}\n\nFollow-up questions:
    """

    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful assistant generating follow-up questions."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=100,
        n=1,
        temperature=0.2
    )
    
    follow_up_questions = response.choices[0].message.content.strip().split("\n")
    return [q.strip() for q in follow_up_questions[:2] if q.strip()]

import re

import re
import asyncio
from typing import List, Dict, Any

async def esg_analysis_stream(user_query: str):
    try:
        logger.info(f"Processing query: {user_query}")
        
        # Step 1: Search for relevant information
        search_results = await search_multimodal(user_query)
        logger.info(f"Found {len(search_results)} search results")
        
        # Step 2: Process search results
        context_parts = await asyncio.gather(*[asyncio.to_thread(process_search_result, item) for item in search_results])
        context = "".join(context_parts)
        logger.info(f"Processed search results into context of length {len(context)}")

        # Step 3: Generate response
        response_generator = generate_response_stream(user_query, context)
        full_response = ""
        async for response_chunk in response_generator:
            full_response += response_chunk
        logger.info(f"Generated full response of length {len(full_response)}")

        # Step 4: Split the response into main content and sources
        parts = full_response.split("Top 5 most relevant sources used to generate the response:", 1)
        main_response = parts[0].strip() if parts else full_response
        sources = parts[1].strip() if len(parts) > 1 else ""

        logger.info(f"Main response length: {len(main_response)}, Sources length: {len(sources)}")

        # Step 5: Generate follow-up questions
        follow_up_questions = await generate_follow_up_questions(main_response)
        logger.info(f"Generated {len(follow_up_questions)} follow-up questions")

        return main_response, sources, follow_up_questions

    except Exception as e:
        logger.error(f"Error in esg_analysis_stream: {str(e)}", exc_info=True)
        raise  # Re-raise the exception after logging it

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
async def ask():
    try:
        user_question = request.json['question']
        main_response, sources, follow_up_questions = await esg_analysis_stream(user_question)
        response_data = {
            'response': main_response,
            'sources': sources,
            'follow_up_questions': follow_up_questions[:2]  # Limit to 2 follow-up questions
        }
        print("Sending response:", response_data)
        return jsonify(response_data)
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return jsonify({'error': 'An error occurred while processing your request'}), 500
    

@app.route('/<path:filename>')
def serve_pdf(filename):
    try:
        return send_file(filename)
    except Exception as e:
        app.logger.error(f"Error serving PDF {filename}: {str(e)}")
        return f"Error: Could not serve file {filename}", 404

@app.route('/data/<path:filename>')
def serve_pdf(filename):
    try:
        return send_from_directory('data', filename)
    except FileNotFoundError:
        return f"Error: File {filename} not found", 404

@app.route('/status')
async def status():
    return jsonify(connection_status)

@app.route('/test-pdf')
def test_pdf():
    return '''
    <h1>PDF Test</h1>
    <iframe src="./data/DS950 - Versal Architecture and Product Data Sheet - Overview - v2.2 - 240604.pdf" width="100%" height="500px"></iframe>
    '''

if __name__ == '__main__':
    asyncio.run(initialize_weaviate_client())
    app.run(debug=True)