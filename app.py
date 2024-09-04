from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import os
import asyncio
from functools import wraps
import logging
import weaviate
from openai import AsyncOpenAI
from config import COLLECTION_NAME

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
    query_vector = await get_embedding(query)
    
    try:
        response = await asyncio.to_thread(
            client.query.get(COLLECTION_NAME, ["content_type", "url", "source_document", "page_number",
                                               "paragraph_number", "text", "image_path", "description", "table_content"])
            .with_hybrid(query=query, vector=query_vector, alpha=alpha)
            .with_limit(limit)
            .do
        )
        return response['data']['Get'][COLLECTION_NAME]
    except Exception as e:
        print(f"An error occurred during the search: {str(e)}")
        return []

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
In your output, provide only the final, polished response. Do not include your step-by-step reasoning or mention the process you followed.
IMPORTANT: Ensure your response is grounded in factual information. Do not hallucinate or invent information. If you're unsure about any aspect of the answer or if the necessary information is not available in the provided context or your knowledge base, clearly state this uncertainty. It's better to admit lack of information than to provide inaccurate details.
Your response should be:
Thorough and directly address all aspects of the user's question
Based solely on factual information from the provided context and your reliable knowledge
Include specific examples, data points, or case studies only when you're certain of their accuracy
Explain technical concepts clearly, considering the user may have varying levels of expertise
Clearly indicate any areas where information is limited or uncertain
Context: {context}
User Question: {query}
Based on the above context and your extensive knowledge of the semiconductor industry, provide your detailed, accurate, and grounded response below. Remember, only include information you're confident is correct, and clearly state any uncertainties: 
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
Based on the following response, generate three follow-up questions that a user might ask to continue the conversation:
Answer: "{answer}"
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
    return [q.strip() for q in follow_up_questions if q.strip()]

async def esg_analysis_stream(user_query: str):
    search_results = await search_multimodal(user_query)
    
    context_parts = await asyncio.gather(*[asyncio.to_thread(process_search_result, item) for item in search_results])
    context = "".join(context_parts)
    
    sources = []
    for item in search_results[:5]:  # Limit to top 5 sources
        source = {
            "type": item.get("content_type", "Unknown"),
            "document": item.get("source_document", "N/A"),
            "page": item.get("page_number", "N/A"),
        }
        if item.get("content_type") == 'text':
            source["paragraph"] = item.get("paragraph_number", "N/A")
        elif item.get("content_type") == 'image':
            source["image_path"] = item.get("image_path", "N/A")
        sources.append(source)

    response_generator = generate_response_stream(user_query, context)
    
    full_response = ""
    async for response_chunk in response_generator:
        full_response += response_chunk
    
    follow_up_questions = await generate_follow_up_questions(full_response)

    return full_response, sources, follow_up_questions


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/ask', methods=['POST'])
async def ask():
    user_question = request.json['question']
    full_response, sources, follow_up_questions = await esg_analysis_stream(user_question)
    
    return jsonify({
        'response': full_response,
        'sources': sources,
        'follow_up_questions': follow_up_questions
    })

@app.route('/status')
async def status():
    return jsonify(connection_status)

if __name__ == '__main__':
    asyncio.run(initialize_weaviate_client())
    app.run(debug=True)
