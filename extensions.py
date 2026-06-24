from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import create_client
from openai import OpenAI

from config import Config


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100 per hour"]
)


supabase = create_client(
    Config.SUPABASE_URL,
    Config.SUPABASE_SERVICE_ROLE
)


openai_client = OpenAI(
    api_key=Config.OPENAI_API_KEY
)
