import weaviate
import os
from dotenv import load_dotenv
load_dotenv()

# Set these environment variables
URL = os.getenv('WCS_URL')
APIKEY = os.getenv('WCS_API_KEY')
OPENAI_API_TOKEN = os.getenv('OPENAI_API_TOKEN')

# Connect to a WCS instance
client = weaviate.connect_to_wcs(
    cluster_url=URL,
    auth_credentials=weaviate.auth.AuthApiKey(APIKEY),
    # headers = {
    #     "X-OpenAI-Api-Key": OPENAI_API_TOKEN
    # }
)