import weaviate
import json

client = weaviate.Client("http://localhost:8080")

# Check if Weaviate is ready
print("Weaviate ready:", client.is_ready())

# Define the class schema
class_obj = {
    "class": "TutorialChunk",
    "description": "Autodesk Revit tutorial chunks (hierarchical)",
    "vectorizer": "text2vec-transformers",
    "moduleConfig": {
        "text2vec-transformers": {
            "vectorizeClassName": False
        }
    },
    "properties": [
        {"name": "page_title", "dataType": ["text"]},
        {"name": "toc_title", "dataType": ["text"]},
        {"name": "chunk_text", "dataType": ["text"]},
        {"name": "page_url", "dataType": ["text"]},
        {"name": "breadcrumb", "dataType": ["text[]"]},
        {"name": "chunk_index", "dataType": ["int"]},
        {"name": "video_links", "dataType": ["text[]"]},
        {"name": "category", "dataType": ["text"]},
        {"name": "time_required", "dataType": ["text"]},
        {"name": "tutorial_files_used", "dataType": ["text[]"]}
    ]
}

try:
    # Create the class
    client.schema.create_class(class_obj)
    print("Class created successfully!")
    
    # Verify the schema was created
    schema = client.schema.get()
    print("Current schema:", json.dumps(schema, indent=2))
    
except Exception as e:
    print("Error creating class:", str(e))
    print("Trying alternative approach...")
    
    # Try creating the full schema
    try:
        full_schema = {"classes": [class_obj]}
        client.schema.create(full_schema)
        print("Full schema created successfully!")
    except Exception as e2:
        print("Alternative approach also failed:", str(e2))
