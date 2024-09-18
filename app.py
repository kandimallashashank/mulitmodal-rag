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
    prompt = f"""You are an advanced AI assistant specializing in technology and communications, with a focus on MaxLinear's products and Wi-Fi technology. Your task is to provide accurate, comprehensive, and insightful answers to queries based on the provided information and your general knowledge.

Context: {context}

This context contains information from recent articles about MaxLinear and Wi-Fi technology. Use this as your primary source of information.

Query: {query}

Instructions:
1. Carefully analyze the query and the provided context.
2. Formulate a response that directly addresses the query, prioritizing information from the given context.
3. Structure your response as follows:
   a. Start with a concise summary (2-3 sentences) that directly answers the main point of the query.
   b. Provide a detailed explanation, breaking it down into relevant subsections if necessary.
   c. Include specific examples, technical details, or comparisons where appropriate.
   d. Discuss any potential implications or future developments related to the query.

4. Cite your sources using the following format:
   [1] for the first source, [2] for the second, and so on.

5. If the provided context doesn't fully address the query:
   a. Clearly state what information is missing or uncertain.
   b. Supplement with your general knowledge, clearly distinguishing it from the provided context.
   c. Suggest potential areas for further research or inquiry.

6. Maintain objectivity:
   - Present factual information without bias.
   - If a topic is controversial or has multiple viewpoints, acknowledge this.

7. Use technical language appropriate for an audience familiar with networking and communications technology, but provide brief explanations for highly specialized terms.

8. If relevant, include numerical data, statistics, or technical specifications to support your points.

9. Consider the recency of the information in the context, prioritizing the most up-to-date data when appropriate.

10. Conclude your response with a brief summary of the key points and, if applicable, potential next steps or areas for further consideration.

11. Give the answer in a conversational tone and very concisely maintaining the main points. Do not use any titles or headings in your response.

12. If you are not sure about the answer, say "I don't know" or "I'm not sure". Use your general knowledge to answer the question. Also make sure to mention that you are not sure about the answer.

13. Answer general questions like Hi, Hello, How are you, etc. with a greeting.(No Source needed)

Remember, your goal is to provide the most helpful, accurate, and comprehensive answer possible, based primarily on the provided content and supplemented by your general knowledge when necessary. Ensure that your response is coherent, well-structured, and directly addresses the query.

After your response, on a new line, write "Top 5 most relevant sources used to generate the response:" followed by the top 5 most relevant sources. Rank them based on their relevance and importance to the answer. Format each source as follows:
[Rank]. [Content Type] from [Document Name] (PDF [PDF LINK])

For example:
Sources:
1. Press Release from MaxLinear Announces Second Quarter 2024 Financial Results https://www.maxlinear.com/wp-content/uploads/2024/05/MaxLinear-Announces-Second-Quarter-2024-Financial-Results.pdf  
2. Product Information from MaxLinear's Wi-Fi CERTIFIED 7 Solutions https://www.maxlinear.com/wp-content/uploads/2024/05/MaxLinear-Announces-Second-Quarter-2024-Financial-Results.pdf
3. News Article from Wi-Fi Alliance Introduces Wi-Fi CERTIFIED 7 https://www.maxlinear.com/wp-content/uploads/2024/05/MaxLinear-Announces-Second-Quarter-2024-Financial-Results.pdf

IMPORTANT NOTE: Only provide sources if it is referenced or mentioned in the response. Also dont repeat the same source again and again.
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
def serve_pdf_from_data(filename):
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
    app.run(debug=True, host='0.0.0.0', port=5000)