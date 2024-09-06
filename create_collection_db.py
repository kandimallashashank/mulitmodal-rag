import weaviate
import os
from dotenv import load_dotenv
load_dotenv()

# Set these environment variables
URL = os.get('WCS_URL')
APIKEY = os.get('WCS_API_KEY')
OPENAI_API_TOKEN = os.get('OPENAI_API_TOKEN')

# Connect to a WCS instance
client = weaviate.connect_to_wcs(
    cluster_url=URL,
    auth_credentials=weaviate.auth.AuthApiKey(APIKEY),
    headers = {
        "X-OpenAI-Api-Key": OPENAI_API_TOKEN
    }
)