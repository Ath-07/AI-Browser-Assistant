from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI # type: ignore

load_dotenv("../.env")

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0
)

memory = []