import os
import base64
from tqdm import tqdm
from PIL import Image
import io
import os
from dotenv import load_dotenv
import weaviate
from openai import OpenAI
from anthropic import Anthropic
from unstructured.partition.pdf import partition_pdf
from unstructured.documents.elements import NarrativeText, Table, Image as UnstructuredImage
from weaviate.util import generate_uuid5

load_dotenv()
# Set up environment variables and API keys
OPENAI_API_KEY = os.get('OPENAI_API_KEY')
ANTHROPIC_API_KEY = os.get('ANTHROPIC_API_KEY')
WCS_URL = os.get('WCS_URL')
WCS_API_KEY = os.get('WCS_API_KEY')

os.environ['OPENAI_API_KEY'] = OPENAI_API_KEY

# Initialize clients
openai_client = OpenAI(api_key=OPENAI_API_KEY)
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
weaviate_client = weaviate.connect_to_wcs(
    cluster_url=WCS_URL,
    auth_credentials=weaviate.auth.AuthApiKey(WCS_API_KEY),
    headers={"X-OpenAI-Api-Key": OPENAI_API_KEY}
)

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_embedding(text):
    response = openai_client.embeddings.create(
        input=text,
        model="text-embedding-3-large"
    )
    return response.data[0].embedding

def summarize_image(img_base64, prompt):
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

def process_pdf(pdf_path, output_dir):
    pdf_name = os.path.basename(pdf_path)
    pdf_output_dir = os.path.join(output_dir, pdf_name.replace('.pdf', ''))
    os.makedirs(pdf_output_dir, exist_ok=True)
    
    elements = partition_pdf(
        filename=pdf_path,
        extract_images_in_pdf=True,
        infer_table_structure=True,
        strategy="hi_res",
        extract_image_block_types=["Image", "Table"],
        extract_image_block_output_dir=pdf_output_dir
    )
    
    text_data = []
    image_data = []
    table_data = []
    
    for idx, element in enumerate(elements):
        if isinstance(element, NarrativeText):
            text_data.append({
                "source_document": pdf_path,
                "page_number": element.metadata.page_number,
                "paragraph_number": idx,
                "text": element.text
            })
        elif isinstance(element, (UnstructuredImage, Table)):
            image_path = element.metadata.image_path if hasattr(element.metadata, 'image_path') else None
            if image_path and os.path.exists(image_path):
                base64_image = encode_image(image_path)
                description = summarize_image(base64_image, "Describe this image or table in detail.")
                
                data = {
                    "source_document": pdf_path,
                    "page_number": element.metadata.page_number,
                    "image_path": image_path,
                    "description": description,
                    "base64_encoding": base64_image
                }
                
                if isinstance(element, Table):
                    data["table_content"] = str(element)
                    table_data.append(data)
                else:
                    image_data.append(data)
    
    return text_data, image_data, table_data

def ingest_data(collection, data, data_type):
    with collection.batch.dynamic() as batch:
        for item in tqdm(data, desc=f"Ingesting {data_type} data"):
            vector = get_embedding(item['text'] if data_type == 'text' else item['description'])
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
            elif data_type == 'table':
                properties.update({
                    "table_content": item['table_content'],
                    "description": item['description']
                })
            
            uuid = generate_uuid5(f"{item['source_document']}_{item['page_number']}_{data_type}_{item.get('paragraph_number', '') or item.get('image_path', '')}")
            batch.add_object(properties=properties, uuid=uuid, vector=vector)

def process_pdf_directory(pdf_dir, output_dir):
    all_text_data = []
    all_image_data = []
    all_table_data = []
    
    for filename in os.listdir(pdf_dir):
        if filename.endswith('.pdf'):
            pdf_path = os.path.join(pdf_dir, filename)
            print(f"Processing {filename}...")
            text_data, image_data, table_data = process_pdf(pdf_path, output_dir)
            all_text_data.extend(text_data)
            all_image_data.extend(image_data)
            all_table_data.extend(table_data)
    
    return all_text_data, all_image_data, all_table_data

def main(pdf_dir, output_dir, collection_name):
    # Process all PDFs in the directory
    text_data, image_data, table_data = process_pdf_directory(pdf_dir, output_dir)
    
    # Get or create Weaviate collection
    collection = weaviate_client.collections.get_or_create(
        name=collection_name,
        vectorizer_config=weaviate.classes.Configure.Vectorizer.none(),
        properties=[
            {"name": "source_document", "dataType": ["text"]},
            {"name": "page_number", "dataType": ["int"]},
            {"name": "paragraph_number", "dataType": ["int"]},
            {"name": "text", "dataType": ["text"]},
            {"name": "image_path", "dataType": ["text"]},
            {"name": "description", "dataType": ["text"]},
            {"name": "base64_encoding", "dataType": ["blob"]},
            {"name": "table_content", "dataType": ["text"]},
            {"name": "content_type", "dataType": ["text"]}
        ]
    )
    
    # Ingest data
    ingest_data(collection, text_data, 'text')
    ingest_data(collection, image_data, 'image')
    ingest_data(collection, table_data, 'table')
    
    print("Data ingestion complete.")

if __name__ == "__main__":
    pdf_dir = "./data/pdfs"  # Replace with your PDF directory path
    output_dir = "./data/images"
    collection_name = "RAGESGDocuments3"
    main(pdf_dir, output_dir, collection_name)