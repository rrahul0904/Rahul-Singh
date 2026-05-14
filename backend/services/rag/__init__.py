__all__ = ["RagIndexer", "RagRetriever"]


def __getattr__(name):
    if name == "RagIndexer":
        from services.rag.indexer import RagIndexer

        return RagIndexer
    if name == "RagRetriever":
        from services.rag.retriever import RagRetriever

        return RagRetriever
    raise AttributeError(name)
