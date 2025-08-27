import weaviate

def main():
    client = weaviate.Client("http://127.0.0.1:8080", timeout_config=(10, 120))
    res = client.query.aggregate("TutorialChunk").with_meta_count().do()
    cnt = res["data"]["Aggregate"]["TutorialChunk"][0]["meta"]["count"]
    print(f"TutorialChunk objects: {cnt}")

if __name__ == "__main__":
    main()
