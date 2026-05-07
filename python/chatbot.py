
import os
import sys
import faiss
import re
import json
import traceback
import warnings
import docx
import PyPDF2

from groq import Groq
from openai import OpenAI
from openai import AzureOpenAI
from anthropic import Anthropic

from uuid import uuid4
from docx import Document
from typing import List
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.docstore import InMemoryDocstore
from langchain_core.documents import Document
from langchain.embeddings.base import Embeddings


warnings.filterwarnings("ignore")


# Model defaults can live in code; API keys should stay in the environment.
os.environ.setdefault("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
os.environ.setdefault("GROQ_MODEL", "llama-3.3-70b-versatile")
os.environ.setdefault("OPENAI_MODEL", "gpt-5-chat-latest")
os.environ.setdefault(
    "VERTEXAI_BASE_URL",
    "https://LOCATION-aiplatform.googleapis.com/v1beta1/projects/PROJECT_ID/locations/LOCATION/endpoints/openapi",
)
os.environ.setdefault("VERTEXAI_MODEL", "google/gemini-2.5-flash-lite")
os.environ.setdefault("AZURE_API_ENDPOINT", "https://ENDPOINT.openai.azure.com")
os.environ.setdefault("AZURE_API_DEPLOYMENT", "YOUR_DEPLOYMENT")
os.environ.setdefault("AZURE_API_VERSION", "2024-05-01-preview")
os.environ.setdefault("AZURE_API_MODEL_NAME", "gpt-5-mini")

# Required for SentenceTransformer
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# GLOBALS
TEMPERATURE = 0.1
MAX_TOKENS = 8192

# SentenceTransformer embeddings
class SentenceTransformerEmbeddings(Embeddings):
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.model.encode(texts)
    def embed_query(self, query: str) -> List[float]:
        return self.model.encode(query)

# Initialize SentenceTransformer embeddings
embeddings = SentenceTransformerEmbeddings()


def replace_multiple_whitespaces(text):
    text = re.sub(r'\t{2,}', '\t', text)
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r' {2,}', ' ', text)
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    return text

def summarize_pdf(file_path):
    try:
        if file_path is None or len(file_path) == 0:
            return None
        summary = ''
        with open(file_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                summary += page.extract_text()
        return summary
    except Exception as e:
        return None
    
def summarize_docx(file_path):
    try:
        if ( file_path == None or len(file_path) == 0):
            return None
        summary = ''
        doc = docx.Document(file_path)
        for paragraph in doc.paragraphs:
            text = '\n'.join([paragraph.text])
        return summary
    except Exception as e:
        return None
   

def summarize_txt(file_path):
    try:
        if ( file_path == None or len(file_path) == 0):
            return None
        summary = ''
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            summary = file.read()
        return summary
    except Exception as e:
        return None
    

# generate the documents
def generate_doc_embeddings(text, filename):
    try:
        if ( text == None or len(text) == 0):
            print("ERROR: Invalid text files.")
            return None
        if ( filename == None or len(filename) == 0):
            print("ERROR: Invalid filename.")
            return None
        
        # split text into overlapping chunks
        text_splitter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", ' ', ''],
            chunk_size = 1000,
            chunk_overlap = 200,
            length_function = len,
            is_separator_regex = False
        )

        # Use the text splitter to split the text
        chunks = text_splitter.split_text(text)

        # Create a list of documents
        documents = []
        for chunk in chunks:
            content = replace_multiple_whitespaces(chunk)
            if (len(content) == 0): continue
            documents.append(Document(metadata={"file":filename}, page_content=content))
                
        return documents
    except Exception as e:
        print("Exception: [", sys.exc_info()[0].__name__, "] ",  os.path.basename(sys.exc_info()[2].tb_frame.f_code.co_filename), "(", sys.exc_info()[2].tb_lineno, "): ", e, flush=True)
    return None


def build_rag_db(dir, db):
    try:
        if ( dir == None or len(dir) == 0):
            print("ERROR: Invalid directory.")
            return
        elif ( db == None or len(db) == 0):
            print("ERROR: Invalid vector database directory.")
            return
                
        # Create FAISS index
        index = faiss.IndexFlatL2(len(embeddings.embed_query("hello world")))
        vector_store = FAISS(
            embedding_function=embeddings,
            index=index,
            docstore=InMemoryDocstore(),
            index_to_docstore_id={},
        )
              
        # Iterate through all the files in the directory
        for filename in os.listdir(dir):
            filepath = os.path.join(dir, filename)
            print (f"Processing file: {filepath}")
            text = None
            if filepath.endswith('.pdf'):
                text = summarize_pdf(filepath)
            elif filepath.endswith('.txt'):
                text = summarize_txt(filepath)
            elif filepath.endswith('.docx'):
                text = summarize_docx(filepath)

            if ( text == None or len(text) == 0): continue

            # generate the documents
            doc_embeddings = generate_doc_embeddings(text, filepath)
            
            # Generate unique IDs for each embedding and add to the vector store
            uuids = [str(uuid4()) for _ in range(len(doc_embeddings))]
            vector_store.add_documents(documents=doc_embeddings, ids=uuids)

        # Save the vector store
        vector_store.save_local(db)
    except Exception as e:
        print("Exception: [", sys.exc_info()[0].__name__, "] ",  os.path.basename(sys.exc_info()[2].tb_frame.f_code.co_filename), "(", sys.exc_info()[2].tb_lineno, "): ", e, flush=True)
        #traceback.print_exc()


def query_groq(prompt):
    try:      
        client = Groq()
        response = client.chat.completions.create(
            messages=prompt,
            model=os.environ.get("GROQ_MODEL"), 
            response_format={"type": "json_object"},
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            top_p=1,
            stop=None,
            stream=False,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("Exception: [", sys.exc_info()[0].__name__, "] ",  os.path.basename(sys.exc_info()[2].tb_frame.f_code.co_filename), "(", sys.exc_info()[2].tb_lineno, "): ", e, flush=True)
    return None

def query_openai(prompt):
    try:      
        client = OpenAI()
        response = client.chat.completions.create(
            messages=prompt,
            model=os.environ.get("OPENAI_MODEL"), 
            response_format={"type": "json_object"},
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            top_p=1,
            stop=None,
            stream=False,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("Exception: [", sys.exc_info()[0].__name__, "] ",  os.path.basename(sys.exc_info()[2].tb_frame.f_code.co_filename), "(", sys.exc_info()[2].tb_lineno, "): ", e, flush=True)
    return None

def query_azure(prompt):
    try:
        # Initialize client
        client = AzureOpenAI(
            api_key = os.environ.get("AZURE_API_KEY"),
            api_version = os.environ.get("AZURE_API_VERSION"),
            azure_endpoint = os.environ.get("AZURE_API_ENDPOINT")
        )

        # Submit the request to the OpenAI API
        response = client.chat.completions.create(
            model = os.environ.get("AZURE_API_DEPLOYMENT"),
            response_format={ "type": "json_object" },
            messages = prompt,
            temperature = TEMPERATURE,
            max_tokens = MAX_TOKENS,
            n = 1
        )
        return response.choices[0].message.content.strip()        
    except Exception as e:
        print("Exception: [", sys.exc_info()[0].__name__, "] ",  os.path.basename(sys.exc_info()[2].tb_frame.f_code.co_filename), "(", sys.exc_info()[2].tb_lineno, "): ", e, flush=True)
    return None

def query_anthropic(prompt):
    try:      
        client = Anthropic()
        response = client.messages.create(
            system=prompt[0]["content"],
            messages=prompt[1:],
            model=os.environ.get("ANTHROPIC_MODEL"), 
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            # top_p=1,
            stream=False,
        )
        return response.content[0].text.strip()
    except Exception as e:
        print("Exception: [", sys.exc_info()[0].__name__, "] ",  os.path.basename(sys.exc_info()[2].tb_frame.f_code.co_filename), "(", sys.exc_info()[2].tb_lineno, "): ", e, flush=True)
    return None

def query_vertexai(prompt):
    try:      
        client = OpenAI(
            base_url=os.environ.get("VERTEXAI_BASE_URL"),
            api_key=os.environ.get("VERTEXAI_API_KEY")
        )
        response = client.chat.completions.create(
            messages=prompt,
            model=os.environ.get("VERTEXAI_MODEL"), 
            response_format={"type": "json_object"},
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            top_p=1,
            stop=None,
            stream=False,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("Exception: [", sys.exc_info()[0].__name__, "] ",  os.path.basename(sys.exc_info()[2].tb_frame.f_code.co_filename), "(", sys.exc_info()[2].tb_lineno, "): ", e, flush=True)
    return None



def rag_query(dir, query, history=[]):
    response_text = None

    try:
        if ( dir == None or len(dir) == 0):
            print("ERROR: Invalid vector database directory.")
            return
        elif ( query == None or len(query) == 0):
            print("ERROR: Invalid query.")
            return

        # Load the vector store (make sure embeddings and model are properly set up)
        vector_db = FAISS.load_local(dir, embeddings, allow_dangerous_deserialization=True)
        
        # Perform similarity search based on the user's query
        results = vector_db.similarity_search(query, k=10)
        
        # Iterate through the context and format them in a human-readable way
        context = [{"file": doc.metadata["file"], "content": doc.page_content} for doc in results]

        # Create the system and user messages
        system_message = """
        You are a friendly AI assistant. Your job is to provide details about documents and answer questions. 
        You are provided the following information: 
            1. the query
            2. relevant context from the documents in json format

        Here's how you should proceed: 
            1. Understand the query. 
            2. Understand the documents that have been made available. 
            3. Create a draft of an answer to the question, this is based on the things you get from the documents shared.
            4. Review the draft then create the final answer to ensure it's correct and good. 
            5. If you don't know the answer or don't have sufficient information to respond, you should say so.
            6. You must only output JSON format with the following structure: the "answer", and a list of unique "references" which are only the file names used to generate the answer.

        Example output:
        {
            "answer": "The answer to the query",
            "references": ["file1.pdf", "file2.txt"]
        }
        """
        
        user_message = f"QUERY: {query}\nCONTEXT:\n{context}"
        
        # Combine the messages into a single prompt
        messages = []
        messages.append({"role": "system", "content": f"{system_message}"})
        messages.extend(history)
        messages.append({"role": "user", "content": f"{user_message}"})

        # Query the LLM
        response_text = query_anthropic(messages)
        #response_text = query_groq(messages)
        #response_text = query_openai(messages)
        #response_text = query_vertexai(messages)

        # Parse the response
        if ( response_text == None or len(response_text) == 0 ):
            print("ERROR: Invalid response from the language model.")
            return None

        # Parse the response and return the output 
        if response_text.startswith("```"):
            response_text = response_text.strip("`")
            if response_text.startswith("json"):
                response_text = response_text[4:].strip()

        output = json.loads(response_text, strict=False)
        return output
    except Exception as e:
        print("Exception: [", sys.exc_info()[0].__name__, "] ",  os.path.basename(sys.exc_info()[2].tb_frame.f_code.co_filename), "(", sys.exc_info()[2].tb_lineno, "): ", e, flush=True)
        print(json.dumps(response_text))

def run_rag_process(db):
    history = []
    response = None

    # run the RAG process, including historical messages for context
    while True:
        try:    
            # Get the query from the user
            query = input("\nQuery: ")
            if query == "exit" or query == "quit": break

            # Get the response from the RAG model
            response = rag_query(db, query, history)
            if ( response == None or len(response) == 0 ):
                print("ERROR: Invalid response from the RAG model.")
                continue

            # Print the response
            #print(f"\n{json.dumps(response, indent=4)}\n")
            print(f"\n{response["answer"]}\n")
            if ( "references" in response and len(response["references"]) > 0):
                print(f"References:\n{'\n'.join(response["references"])}\n")
            print("-------------------------------------------\n")

            # Add the query and response to the historical messages list
            if ( response != None and "answer" in response and len(response["answer"]) > 0):
                history.append({"role": "user", "content": query})
                history.append({"role": "assistant", "content": response["answer"]})

            # keep only the last 10 messages for context
            if ( len(history) > 10 ): history = history[-10:]
        except Exception as e:
            print("Exception: [", sys.exc_info()[0].__name__, "] ",  os.path.basename(sys.exc_info()[2].tb_frame.f_code.co_filename), "(", sys.exc_info()[2].tb_lineno, "): ", e, flush=True)
            print(response)
    return


def main():
    try:
        dir = None
        db = None
        build = False

        # process arguments
        args = iter(sys.argv[1:])  
        for arg in args:
            if ( arg == '-d' or arg == '--dir'):
                dir = next(args)
            elif ( arg == '-db' or arg == '--database'):
                db = next(args)
            elif ( arg == '-b' or arg == '--build'):
                build = True
            else:
                print("Invalid argument: " + arg)
                return
        
        # build the RAG database using FAISS
        if ( build ): build_rag_db(dir, db)

        # run the RAG process
        run_rag_process(db)

    except Exception as e:
        print("Exception: [", sys.exc_info()[0].__name__, "] ",  os.path.basename(sys.exc_info()[2].tb_frame.f_code.co_filename), "(", sys.exc_info()[2].tb_lineno, "): ", e, flush=True)
    return


if __name__ == "__main__":
    main()
