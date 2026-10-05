import os
import io
import json
import uuid
from typing import List

import pandas as pd
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
from PIL import Image
from fpdf import FPDF

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request, Form
from fastapi.responses import JSONResponse, Response, FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv
import jwt
from authlib.integrations.starlette_client import OAuth
from sqlalchemy.orm import Session

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate, MessagesPlaceholder
from langchain_core.documents import Document
from langchain_classic.chains import create_history_aware_retriever, create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.chains.summarize import load_summarize_chain
from langchain_text_splitters import RecursiveCharacterTextSplitter

from database import get_db, User, ChatSession, ChatMessage, UploadLog

load_dotenv()

app = FastAPI(title="Intelligent Study Assistant API")

# Setup session for OAuth
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", "super-secret-session-key"))

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

DATA_DIR = "data"
CHROMA_DIR = "chroma_db"
TRAIN_DIR_BASE = "training_data"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CHROMA_DIR, exist_ok=True)
os.makedirs(TRAIN_DIR_BASE, exist_ok=True)

# OAuth Setup
oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID', 'dummy_id_replace_me'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET', 'dummy_secret_replace_me'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)
JWT_SECRET = os.environ.get("JWT_SECRET", "super-secret-jwt-key")

# --- AUTH DEPENDENCY ---
def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("auth_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("user_id")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- AUTH ROUTES ---
@app.get("/auth/login")
async def login(request: Request):
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/callback")
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        return {"error": str(e), "message": "Failed to authorize. Make sure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set in .env."}
        
    user_info = token.get('userinfo')
    if not user_info:
        raise HTTPException(status_code=400, detail="Missing user info")
        
    user = db.query(User).filter(User.email == user_info['email']).first()
    if not user:
        user = User(
            google_id=user_info['sub'],
            email=user_info['email'],
            name=user_info.get('name')
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
    jwt_token = jwt.encode({"user_id": user.id}, JWT_SECRET, algorithm="HS256")
    response = RedirectResponse(url="/")
    response.set_cookie(key="auth_token", value=jwt_token, httponly=True, max_age=86400*7) # 7 days
    return response

@app.get("/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "name": current_user.name, "email": current_user.email}

@app.post("/auth/logout")
async def logout():
    response = JSONResponse({"status": "success"})
    response.delete_cookie("auth_token")
    return response


from langchain_core.retrievers import BaseRetriever
from typing import List

class PrioritizedRetriever(BaseRetriever):
    retriever_session: BaseRetriever
    retriever_admin: BaseRetriever

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> List[Document]:
        session_docs = self.retriever_session.invoke(query)
        admin_docs = self.retriever_admin.invoke(query)
        
        seen = set()
        final_docs = []
        
        # Tag session docs so they are ALWAYS treated as User Uploads in this chat
        for doc in session_docs:
            doc.metadata["is_current_session"] = True
            if doc.page_content not in seen:
                seen.add(doc.page_content)
                final_docs.append(doc)
                
        # Tag admin docs (fallback)
        for doc in admin_docs:
            if doc.page_content not in seen:
                doc.metadata["is_current_session"] = False
                seen.add(doc.page_content)
                final_docs.append(doc)
                
        return final_docs[:40]

# --- RAG PIPELINE ---
def get_rag_pipeline(user_id: str = None, session_id: str = None, user_email: str = "student@gmail.com", admin_email: str = "admin@gmail.com"):
    if not os.path.exists(CHROMA_DIR) or not os.listdir(CHROMA_DIR):
        return None, None
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vectorstore = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
    
    if session_id:
        retriever_session = vectorstore.as_retriever(search_kwargs={"k": 25, "filter": {"session_id": session_id}})
        retriever_admin = vectorstore.as_retriever(search_kwargs={"k": 15, "filter": {"is_admin": True}})
        retriever = PrioritizedRetriever(retriever_session=retriever_session, retriever_admin=retriever_admin)
    else:
        filter_dict = {"user_id": {"$in": ["global", user_id]}} if user_id else {"user_id": "global"}
        retriever = vectorstore.as_retriever(search_kwargs={"k": 40, "filter": filter_dict})
    
    llm = ChatOllama(model="llama3.2")
    system_prompt = f"""You are an intelligent Study Assistant. You MUST ALWAYS address the student by their name: {{user_name}} (Email: {user_email}) in your greetings.
The 'Global Admin Reference' materials in your context were uploaded by the school administrator (Email: {admin_email}).
Do NOT confuse the student with the administrator, even if they have the exact same name.

Context:
{{context}}"""

    human_prompt = """Previous Conversation History:
{history}

User Request:
{input}

CRITICAL INSTRUCTIONS (MUST OBEY):
1. Your context contains two types of documents: 'Type: User Upload' (documents the student just uploaded) and 'Type: Global Admin Reference' (global curriculum provided by the school admin).
2. If the user asks for a summary, you MUST immediately generate a comprehensive summary using ONLY the chunks marked 'Type: User Upload'. Do NOT ask clarifying questions. Do NOT summarize 'Global Admin Reference' documents.
3. Use 'Global Admin Reference' chunks ONLY if the user asks a general academic question that requires that background knowledge.
4. If the user expresses frustration (e.g., "I don't understand"), respond using an exact Empathy Handler from the dataset.
5. Always follow the Tone Enforcement Protocols.
6. If the user asks about a specific Rule or Protocol by number, check if that exact number exists in the Context. If it does not, you must reply EXACTLY: "I'm sorry, but that rule/protocol is not explicitly listed in my context."
7. Do not guess or make up answers. If the user asks an academic question not found in the Context, reply: "I'm sorry, but that information is not covered in your uploaded study documents." """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", human_prompt)
    ])
    
    # Format each retrieved document chunk securely using metadata
    document_prompt = PromptTemplate(
        input_variables=["page_content", "source", "is_admin", "is_current_session"],
        template="Filename: {{source}}\n{% if is_current_session %}Type: User Upload{% elif is_admin %}Type: Global Admin Reference{% else %}Type: User Upload{% endif %}\nContent: {{page_content}}",
        template_format="jinja2"
    )
    document_chain = create_stuff_documents_chain(llm, prompt, document_prompt=document_prompt)
    
    # History Aware Retriever to contextualize questions based on uploaded files
    contextualize_q_system_prompt = (
        "Given a chat history and the latest user question "
        "which might reference context in the chat history, "
        "formulate a standalone question which can be understood "
        "without the chat history. Do NOT answer the question, "
        "just reformulate it if needed and otherwise return it as is."
    )
    contextualize_q_prompt = ChatPromptTemplate.from_messages([
        ("system", contextualize_q_system_prompt),
        ("human", "History: {history}\n\nLatest Question: {input}"),
    ])
    history_aware_retriever = create_history_aware_retriever(llm, retriever, contextualize_q_prompt)
    
    retrieval_chain = create_retrieval_chain(history_aware_retriever, document_chain)
    return retrieval_chain, retriever, document_chain

# --- CHAT SESSION MANAGEMENT ---
class CreateSessionRequest(BaseModel):
    title: str = "New Conversation"

@app.post("/chat/sessions")
async def create_session(req: CreateSessionRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session_id = str(uuid.uuid4())
    new_sess = ChatSession(id=session_id, user_id=current_user.id, title=req.title)
    db.add(new_sess)
    db.commit()
    return {"id": session_id, "title": req.title}

@app.get("/chat/sessions")
async def get_sessions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = db.query(ChatSession).filter(ChatSession.user_id == current_user.id).order_by(ChatSession.created_at.desc()).all()
    return [{"id": s.id, "title": s.title} for s in sessions]

@app.get("/chat/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sess = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at).all()
    return [{"role": m.role, "content": m.content, "sources": json.loads(m.sources) if m.sources else []} for m in messages]

class ChatStreamRequest(BaseModel):
    message: str
    session_id: str

@app.post("/chat/stream")
async def chat_stream(request: ChatStreamRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sess = db.query(ChatSession).filter(ChatSession.id == request.session_id, ChatSession.user_id == current_user.id).first()
    if not sess:
        return StreamingResponse((f"data: {json.dumps({'type': 'error', 'content': 'Session not found'})}\n\n" for _ in range(1)), media_type="text/event-stream")

    admin_email = os.getenv("ADMIN_EMAIL", "admin@gmail.com")
    rag_chain, retriever, document_chain = get_rag_pipeline(str(current_user.id), request.session_id, current_user.email, admin_email)
    if not rag_chain:
        async def err_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': 'No documents loaded. Please upload files.'})}\n\n"
        return StreamingResponse(err_stream(), media_type="text/event-stream")

    # Fetch history
    history = db.query(ChatMessage).filter(ChatMessage.session_id == request.session_id).order_by(ChatMessage.created_at).all()
    history_str = "\n".join([f"{m.role.capitalize()}: {m.content}" for m in history[-10:]])
    
    # Save user message
    user_msg = ChatMessage(session_id=request.session_id, role="user", content=request.message)
    db.add(user_msg)
    
    # Update session title if it's the first message
    if len(history) == 0:
        sess.title = request.message[:30] + "..."
    db.commit()

    async def generate():
        try:
            yield f"data: {json.dumps({'type': 'status', 'content': 'Searching knowledge base...'})}\n\n"
            
            source_list = []
            full_answer = ""
            
            # Intercept summary requests to force an optimal semantic search query
            # This fixes the issue where typing "give me summary" pulls random/garbage chunks
            is_summary = "summar" in request.message.lower() or "sunmmar" in request.message.lower()
            
            if is_summary:
                # Manually pull the best chunks for a summary
                docs = retriever.invoke("Abstract Introduction Summary Conclusion Main Concepts Overview")
                stream_generator = document_chain.astream({
                    "context": docs, 
                    "input": request.message, 
                    "history": history_str, 
                    "user_name": current_user.name or "Student"
                })
            else:
                # Use standard LCEL chain which has history_aware_retriever built-in
                stream_generator = rag_chain.astream({
                    "input": request.message, 
                    "history": history_str, 
                    "user_name": current_user.name or "Student"
                })
            
            async for chunk in stream_generator:
                # If we are using the full rag_chain, the context comes through in a specific key
                # If we are using document_chain directly, we already have the docs.
                if is_summary:
                    current_docs = docs
                    text_chunk = chunk if isinstance(chunk, str) else chunk.get("text", "")
                else:
                    current_docs = chunk.get("context", []) if isinstance(chunk, dict) else []
                    text_chunk = chunk.get("answer", "") if isinstance(chunk, dict) else chunk
                
                if current_docs and not source_list:
                    for doc in current_docs:
                        source = doc.metadata.get("source", "Unknown Source")
                        page = doc.metadata.get("page", "Unknown Page")
                        source_list.append(f"{source} (Page {page})")
                    source_list = list(dict.fromkeys(source_list))
                    
                    yield f"data: {json.dumps({'type': 'status', 'content': f'Analyzed {len(source_list)} relevant documents. Generating response...'})}\n\n"
                    
                if text_chunk:
                    full_answer += text_chunk
                    yield f"data: {json.dumps({'type': 'token', 'content': text_chunk})}\n\n"
                    
            yield f"data: {json.dumps({'type': 'sources', 'content': source_list})}\n\n"
            yield "data: [DONE]\n\n"
            
            # Save assistant message
            assistant_msg = ChatMessage(
                session_id=request.session_id, 
                role="assistant", 
                content=full_answer,
                sources=json.dumps(source_list)
            )
            # Create a new local db session to avoid thread issues inside generator if needed, 
            # but usually it's fine since we run this sequentially in the async generator.
            # Actually, standard SQLAlchemy Session is not thread-safe. Yielding might switch contexts.
            # It's safer to use a new session here.
            db_gen = get_db()
            db_local = next(db_gen)
            db_local.add(assistant_msg)
            db_local.commit()
            db_local.close()
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            
    return StreamingResponse(generate(), media_type="text/event-stream")

@app.delete("/chat/sessions/{session_id}")
async def delete_session(session_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sess = db.query(ChatSession).filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Try to delete documents from ChromaDB safely
    try:
        embeddings = OllamaEmbeddings(model="nomic-embed-text")
        vectorstore = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
        # ChromaDB API for deleting by metadata might not be directly supported through Langchain's wrapper without getting the underlying collection
        collection = vectorstore._collection
        collection.delete(where={"session_id": session_id})
    except Exception as e:
        print(f"Warning: Could not delete session from ChromaDB: {e}")
        
    db.delete(sess)
    db.commit()
    return {"status": "success", "message": "Session deleted successfully"}

@app.post("/upload")
async def upload_files(
    files: List[UploadFile] = File(...), 
    session_id: str = Form(None),
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    admin_email = os.getenv("ADMIN_EMAIL", "admin@gmail.com")
    is_admin = (current_user.email == admin_email)
    user_id_str = "global" if is_admin else str(current_user.id)
    
    user_train_dir = os.path.join(TRAIN_DIR_BASE, str(current_user.id))
    os.makedirs(user_train_dir, exist_ok=True)
    
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    
    file_names = []
    all_chunks = []
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    success = False
    
    for file in files:
        file_names.append(file.filename)
        # Save to user-specific train dir directly
        train_path = os.path.join(user_train_dir, file.filename)
        
        content = await file.read()
        
        with open(train_path, "wb") as f:
            f.write(content)
            
        # Log upload to DB
        upload_log = UploadLog(user_id=current_user.id, session_id=session_id, filename=file.filename, saved_path=train_path)
        db.add(upload_log)
        
        # Parse based on file type
        if file.filename.lower().endswith('.pdf'):
            try:
                loader = PyPDFLoader(train_path)
                docs = loader.load()
                chunks = splitter.split_documents(docs)
                for chunk in chunks:
                    chunk.page_content = f"Document Name: {file.filename}\n\n" + chunk.page_content
                    chunk.metadata["is_admin"] = is_admin
                    chunk.metadata["user_id"] = user_id_str
                    chunk.metadata["session_id"] = session_id or "default"
                all_chunks.extend(chunks)
                success = True
            except Exception as e:
                print(f"PDF Error on {file.filename}: {e}")
                
        elif file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            try:
                img = Image.open(io.BytesIO(content))
                text = pytesseract.image_to_string(img)
                if text.strip():
                    doc = Document(page_content=f"Document Name: {file.filename}\n\n" + text, metadata={"source": file.filename, "page": 1, "is_admin": is_admin, "user_id": user_id_str, "session_id": session_id or "default"})
                    chunks = splitter.split_documents([doc])
                    all_chunks.extend(chunks)
                    success = True
            except Exception as e:
                print(f"OCR Error on {file.filename}: {e}")
                
        elif file.filename.lower().endswith(('.txt', '.md', '.csv')):
            try:
                from langchain_community.document_loaders import TextLoader
                loader = TextLoader(train_path, encoding='utf-8')
                docs = loader.load()
                chunks = splitter.split_documents(docs)
                for chunk in chunks:
                    chunk.page_content = f"Document Name: {file.filename}\n\n" + chunk.page_content
                    chunk.metadata["is_admin"] = is_admin
                    chunk.metadata["user_id"] = user_id_str
                    chunk.metadata["session_id"] = session_id or "default"
                all_chunks.extend(chunks)
                success = True
            except Exception as e:
                print(f"Text load error on {file.filename}: {e}")

    db.commit()
    
    if success and all_chunks:
        embeddings = OllamaEmbeddings(model="nomic-embed-text")
        vectorstore = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
        
        # Batch insert to prevent Ollama from crashing on large PDFs
        batch_size = 50
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i:i + batch_size]
            vectorstore.add_documents(batch)
            
        success = True

    if success:
        # Add invisible system note to the chat history so the LLM focuses on these files
        if session_id:
            info_msg = ChatMessage(
                session_id=session_id, 
                role="user", 
                content=f"[System Note: I just uploaded the following documents: {', '.join(file_names)}. Please prioritize them for my next questions.]"
            )
            db.add(info_msg)
            db.commit()
            
        return {"status": "success", "message": "Documents vectorized successfully and saved for future training!"}
    return JSONResponse({"status": "error", "message": "Failed to ingest."}, status_code=500)

@app.get("/tools/summary")
async def generate_summary(session_id: str = None, current_user: User = Depends(get_current_user)):
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vectorstore = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
    
    if not session_id:
        raise HTTPException(status_code=400, detail="No active session. Please upload a document to your private pool first.")
        
    summary_retriever = vectorstore.as_retriever(search_kwargs={"k": 10, "filter": {"session_id": session_id}})
    
    # Query for structurally important keywords to pull the most informative chunks
    docs = summary_retriever.invoke("Abstract Introduction Summary Conclusion Main Concepts Overview")
    if not docs:
        raise HTTPException(status_code=400, detail="Please upload a document to your private pool first.")

    llm = ChatOllama(model="llama3.2")
    map_prompt = PromptTemplate.from_template("Summarize the following key educational concepts concisely:\n\n\"{text}\"\n\nCONCISE SUMMARY:")
    combine_prompt = PromptTemplate.from_template("You are an expert tutor. Combine the following chunk summaries into a comprehensive, highly detailed master summary for studying. Use bullet points and clear headings.\n\n\"{text}\"\n\nMASTER STUDY SUMMARY:")
    chain = load_summarize_chain(llm, chain_type="map_reduce", map_prompt=map_prompt, combine_prompt=combine_prompt)
    result = chain.invoke(docs)
    return {"summary": result.get("output_text", str(result))}

@app.get("/tools/quiz")
async def generate_quiz(session_id: str = None, current_user: User = Depends(get_current_user)):
    if not session_id:
        raise HTTPException(status_code=400, detail="No active session. Please upload a document to your private pool first.")
        
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vectorstore = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
    
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5, "filter": {"session_id": session_id}})
    docs = retriever.invoke("What are the core concepts, definitions, and key facts in this document?")
    
    if not docs:
        raise HTTPException(status_code=400, detail="Please upload a document to your private pool first.")
        
    llm = ChatOllama(model="llama3.2")
    context = "\n\n".join([doc.page_content for doc in docs])
    prompt = PromptTemplate.from_template("You are an expert professor. Using ONLY the following context, generate a 5-question multiple-choice practice quiz for your students. Each question must have 4 options (A, B, C, D). Provide the answer key at the very end of the quiz wrapped exactly inside an HTML details block like this:\n<details>\n<summary>Click to view answers</summary>\n(Answers here)\n</details>\nDo not hallucinate information outside of this context.\n\nContext:\n{context}\n\nQuiz:")
    chain = prompt | llm
    response = chain.invoke({"context": context})
    return {"quiz": response.content}

@app.get("/tools/flashcards")
async def generate_flashcards(session_id: str = None, current_user: User = Depends(get_current_user)):
    if not session_id:
        raise HTTPException(status_code=400, detail="No active session. Please upload a document to your private pool first.")
        
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vectorstore = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)
    
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5, "filter": {"session_id": session_id}})
    docs = retriever.invoke("What are the core concepts, definitions, and key facts in this document?")
    
    if not docs:
        raise HTTPException(status_code=400, detail="Please upload a document to your private pool first.")
        
    llm = ChatOllama(model="llama3.2")
    context = "\n\n".join([doc.page_content for doc in docs])
    prompt = PromptTemplate.from_template("Extract exactly 10 key terms and their definitions from the text below. \nFormat each strictly as: Term | Definition\nDo not include any other text.\n\nContext:\n{context}\n\nFlashcards:")
    chain = prompt | llm
    response = chain.invoke({"context": context})
    
    lines = response.content.strip().split('\n')
    data = []
    for line in lines:
        if '|' in line:
            parts = line.split('|', 1)
            data.append({"Term": parts[0].strip(), "Definition": parts[1].strip()})
    
    df = pd.DataFrame(data)
    csv = df.to_csv(index=False)
    return Response(content=csv, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=flashcards.csv"})

class ExportRequest(BaseModel):
    session_id: str

@app.post("/tools/export_pdf")
async def export_pdf(req: ExportRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sess = db.query(ChatSession).filter(ChatSession.id == req.session_id, ChatSession.user_id == current_user.id).first()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")
        
    messages = db.query(ChatMessage).filter(ChatMessage.session_id == req.session_id).order_by(ChatMessage.created_at).all()
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Study Session Notes: {sess.title}", ln=1, align='C')
    pdf.ln(10)
    for msg in messages:
        role = "Student" if msg.role == "user" else "Assistant"
        content = msg.content.encode('latin-1', 'ignore').decode('latin-1')
        pdf.set_font("Arial", 'B', 10)
        pdf.multi_cell(0, 10, txt=f"{role}:")
        pdf.set_font("Arial", '', 10)
        pdf.multi_cell(0, 10, txt=content)
        pdf.ln(5)
    
    output = pdf.output(dest='S')
    if isinstance(output, str):
        output = output.encode('latin-1')
    return Response(content=output, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=session_notes.pdf"})

@app.get("/")
async def root():
    return FileResponse("static/index.html")
