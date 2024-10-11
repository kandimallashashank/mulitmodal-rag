import os
import base64
import asyncio
import aiohttp
from tqdm import tqdm
import weaviate
from dotenv import load_dotenv
from openai import AsyncOpenAI
import anthropic
from unstructured.partition.pdf import partition_pdf
from unstructured.documents.elements import NarrativeText, Table, Image as UnstructuredImage
from weaviate.util import generate_uuid5
import nltk
import logging

import weaviate.classes.config as wc

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()

# Download NLTK data
nltk.download('punkt', quiet=True)

# Set up environment variables and API keys
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
WCS_URL = os.getenv('WCS_URL')
WCS_API_KEY = os.getenv('WCS_API_KEY')

# Initialize clients
openai_client = AsyncOpenAI()
anthropic_client = anthropic.Anthropic()
weaviate_client = weaviate.connect_to_wcs(
    cluster_url=WCS_URL,
    auth_credentials=weaviate.auth.AuthApiKey(WCS_API_KEY),
    headers={"X-OpenAI-Api-Key": OPENAI_API_KEY}
)

def load_prompt(file_path):
    with open(file_path, 'r') as file:
        return file.read().strip()

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

async def get_embedding(text):
    response = await openai_client.embeddings.create(
        input=text,
        model="text-embedding-3-large"
    )
    return response.data[0].embedding

async def summarize_image(img_base64, prompt):
    message = anthropic_client.messages.create(
        model="claude-3-sonnet-20240229",
        max_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_base64
                        }
                    }
                ]
            }
        ]
    )
    return message.content[0].text

async def process_element(element, pdf_path, image_prompt, paragraph_number):
    if isinstance(element, NarrativeText):
        return {
            "type": "text",
            "data": {
                "source_document": pdf_path,
                "page_number": element.metadata.page_number,
                "paragraph_number": paragraph_number,
                "text": element.text
            }
        }
    elif isinstance(element, (UnstructuredImage, Table)):
        page_number = element.metadata.page_number if hasattr(element.metadata, 'page_number') else None
        image_path = element.metadata.image_path if hasattr(element.metadata, 'image_path') else None

        if image_path and os.path.exists(image_path):
            base64_image = encode_image(image_path)
            description = await summarize_image(base64_image, image_prompt)

            return {
                "type": "image",
                "data": {
                    "source_document": pdf_path,
                    "page_number": page_number,
                    "image_path": image_path,
                    "description": description,
                    "base64_encoding": base64_image
                }
            }
        else:
            logging.warning(f"Image file not found or path not available for image on page {page_number}")
            return None


async def process_pdf(pdf_path, output_dir, image_prompt):
    pdf_name = os.path.basename(pdf_path)
    pdf_output_dir = os.path.join(output_dir, pdf_name.replace('.pdf', ''))
    os.makedirs(pdf_output_dir, exist_ok=True)
    
    elements = partition_pdf(
        filename=pdf_path,
        extract_images_in_pdf=True,
        infer_table_structure=True,
        strategy="hi_res",
        #extract_image_block_types=["Image", "Table"],
        extract_image_block_output_dir=pdf_output_dir
    )
    
    tasks = [process_element(element, pdf_path, image_prompt, idx) for idx, element in enumerate(elements)]
    results = await asyncio.gather(*tasks)
    results = [result for result in results if result is not None]
    
    text_data = [item['data'] for item in results if item['type'] == 'text']
    image_data = [item['data'] for item in results if item['type'] == 'image']
    
    return text_data, image_data

async def batch_ingest_data(collection, data, data_type, batch_size=100):
    total_batches = (len(data) + batch_size - 1) // batch_size
    for i in tqdm(range(0, len(data), batch_size), desc=f"Ingesting {data_type} data", total=total_batches):
        batch = data[i:i+batch_size]
        with collection.batch.dynamic() as batch_writer:
            for item in batch:
                vector = await get_embedding(item['text'] if data_type == 'text' else item['description'])
                properties = {
                    "source_document": item['source_document'],
                    "page_number": item['page_number'],
                    "content_type": data_type
                }
                
                if data_type == 'text':
                    properties.update({
                        "paragraph_number": item['paragraph_number'],
                        "text": item['text']
                    })
                elif data_type == 'image':
                    properties.update({
                        "image_path": item['image_path'],
                        "description": item['description'],
                        "base64_encoding": item['base64_encoding']
                    })
                
                uuid = generate_uuid5(f"{item['source_document']}_{item['page_number']}_{data_type}_{item.get('paragraph_number', '') or item.get('image_path', '')}")
                batch_writer.add_object(properties=properties, uuid=uuid, vector=vector)

async def process_pdf_directory(pdf_dir, output_dir, image_prompt):
    all_text_data = []
    all_image_data = []
    
    for filename in os.listdir(pdf_dir):
        if filename.endswith('.pdf'):
            pdf_path = os.path.join(pdf_dir, filename)
            logging.info(f"Processing {filename}...")
            text_data, image_data = await process_pdf(pdf_path, output_dir, image_prompt)
            all_text_data.extend(text_data)
            all_image_data.extend(image_data)
    
    return all_text_data, all_image_data

async def main(pdf_dir, output_dir, collection_name, prompt_file):
    image_prompt = load_prompt(prompt_file)
    
    text_data, image_data = await process_pdf_directory(pdf_dir, output_dir, image_prompt)
    
    if not weaviate_client.collections.exists(collection_name):
        collection = weaviate_client.collections.create(
            name=collection_name,
            properties=[
                {"name": "content", "data_type": wc.DataType.TEXT},
                {"name": "page_number", "data_type": wc.DataType.INT},
                {"name": "total_pages", "data_type": wc.DataType.INT},
                {"name": "file_name", "data_type": wc.DataType.TEXT},
                {"name": "chunk_id", "data_type": wc.DataType.TEXT},
                {"name": "embedding", "data_type": wc.DataType.TEXT},
                {"name": "image", "data_type": wc.DataType.BLOB},
                {"name": "image_embedding", "data_type": wc.DataType.TEXT},
                {"name": "metadata", "data_type": wc.DataType.TEXT}
            ]
        )
    else:
        collection = weaviate_client.collections.get(collection_name)
    
    await batch_ingest_data(collection, text_data, 'text')
    await batch_ingest_data(collection, image_data, 'image')
    
    logging.info("Data ingestion complete.")

if __name__ == "__main__":
    pdf_dir = "./maxlinear/News_Releases" # Directory containing the PDFs to be processed
    output_dir = "./data/images"
    collection_name = "RAGESGDocuments3"
    # prompt_file = "./image_prompt.txt"
    prompt_file = "./image_prompt_maxlinear.txt"
    asyncio.run(main(pdf_dir, output_dir, collection_name, prompt_file))