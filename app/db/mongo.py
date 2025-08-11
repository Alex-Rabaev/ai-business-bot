from pymongo import MongoClient
from pymongo.collection import Collection
from app.config import settings

print(f"Connecting to MongoDB: {settings.MONGO_URI}")

mongo_client = MongoClient(settings.MONGO_URI)
db = mongo_client.get_database(settings.MONGO_DB)

# Collections
users: Collection = db["users"]
conversations: Collection = db["conversations"]