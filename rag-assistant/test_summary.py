import os
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_classic.chains.summarize import load_summarize_chain
from langchain_core.prompts import PromptTemplate
from langchain_core.documents import Document

embeddings = OllamaEmbeddings(model="nomic-embed-text")
vectorstore = Chroma(persist_directory="chroma_db", embedding_function=embeddings)

docs = vectorstore.similarity_search("test", k=1)
print("Docs from Chroma:", len(docs))
if docs:
    print("Doc Metadata:", docs[0].metadata)

llm = ChatOllama(model="llama3.2")
map_prompt = PromptTemplate.from_template("Summarize the following key educational concepts concisely:\n\n\"{text}\"\n\nCONCISE SUMMARY:")
combine_prompt = PromptTemplate.from_template("You are an expert tutor. Combine the following chunk summaries into a comprehensive, highly detailed master summary for studying. Use bullet points and clear headings.\n\n\"{text}\"\n\nMASTER STUDY SUMMARY:")
chain = load_summarize_chain(llm, chain_type="map_reduce", map_prompt=map_prompt, combine_prompt=combine_prompt)

dummy_docs = [Document(page_content="This is a test document to summarize.")]
try:
    result = chain.invoke(dummy_docs)
    print("Success:", result)
except Exception as e:
    import traceback
    traceback.print_exc()
