# Intelligent Study Assistant 🧠📚

An advanced, offline-first Retrieval-Augmented Generation (RAG) platform designed to provide students with a secure, highly personalized, and context-aware AI tutor. 

This project bridges the gap between structured relational data and unstructured semantic search, utilizing local large language models (LLMs) to ensure 100% data privacy and offline capability.

## 🚀 Key Features

*   **Fully Local Inference:** Powered entirely by local models via Ollama. No expensive API keys, no data leaving your machine.
*   **Multi-Tenant RAG Isolation:** Strict vector-space boundaries ensure that users only retrieve context from their own uploaded documents—unless an Admin explicitly uploads global instructional materials.
*   **Dual-Database Synchronization:** Seamlessly binds relational chat histories (SQLite) to dense vector embeddings (ChromaDB), complete with synchronized garbage collection.
*   **Dynamic UI Interception:** An elegant, glassmorphic frontend that parses system-injected metadata blocks via Regex to dynamically render "file attachment" UI bubbles in the chat stream without breaking the LLM's Markdown output.
*   **Google OAuth2 Authentication:** Secure login flow managed by JWT (JSON Web Tokens).

---

## ⚙️ Core Algorithms & Architecture

This application employs a sophisticated pipeline of modern AI algorithms and data structures:

### 1. Vector Search & Retrieval (ChromaDB)
*   **Algorithm:** **HNSW (Hierarchical Navigable Small World) Graphs**.
*   **Purpose:** ChromaDB uses the HNSW algorithm to construct a multi-layered graph for incredibly fast **Approximate Nearest Neighbor (ANN)** searches in high-dimensional space. This allows the system to instantly find the most semantically relevant text chunks among hundreds of thousands of documents.
*   **Metric:** Cosine Similarity / L2 Distance (depending on embedding normalization) to rank document relevance against the user's query vector.

### 2. Dense Vector Embeddings (`nomic-embed-text`)
*   **Algorithm:** **Transformer-based Sentence Embeddings**.
*   **Purpose:** Converts raw text strings into dense, high-dimensional floating-point vectors. The `nomic-embed-text` model is optimized specifically for retrieval tasks, clustering semantically similar concepts (e.g., "OOP" and "Object-Oriented") close together in vector space.

### 3. Text Chunking (`RecursiveCharacterTextSplitter`)
*   **Algorithm:** **Recursive Sliding Window Chunking**.
*   **Purpose:** LLMs have finite context windows. This algorithm recursively splits large textbook PDFs by specific delimiters (paragraphs `\n\n`, then sentences `\n`, then spaces) to create contiguous `1000-character` chunks with a `200-character` overlap. The overlap ensures that semantic context (like the subject of a pronoun) is not lost across chunk boundaries.

### 4. Generative AI Inference (`llama3.2`)
*   **Algorithm:** **Autoregressive Next-Token Prediction (Transformer Decoder)**.
*   **Purpose:** The core brain of the assistant. It receives a heavily engineered `ChatPromptTemplate` containing strict negative constraints (Anti-Hallucination rules) and the retrieved ChromaDB chunks. It then synthesizes a natural, conversational response based *strictly* on the provided context.

### 5. Multi-Tenant Boolean Filtering
*   **Algorithm:** **Metadata Pre-Filtering (Boolean Algebra)**.
*   **Purpose:** Before the HNSW nearest-neighbor search executes, the pipeline applies a strict boolean filter: `{"$or": [{"is_admin": True}, {"session_id": current_session_id}]}`. This guarantees O(1) isolation, completely preventing the LLM from hallucinating answers based on other students' private documents.

### 6. Dynamic Regex UI Parsing
*   **Algorithm:** **Regular Expression (Regex) Pattern Matching**.
*   **Purpose:** The backend injects invisible metadata tags (like `[ATTACHMENT: filename.pdf]`) into the chat stream. The vanilla JavaScript frontend uses a regex state machine to parse the incoming stream, stripping out the hidden tags and replacing them with interactive DOM elements (like document icons) *before* passing the text to `marked.js` for Markdown rendering.

---

## 🛠️ Technology Stack

*   **Backend:** FastAPI (Python), SQLAlchemy (ORM), Uvicorn (ASGI Server).
*   **AI / ML:** LangChain, Ollama, ChromaDB.
*   **Frontend:** Vanilla JavaScript, HTML5, CSS3 (Glassmorphism design, FontAwesome).
*   **Database:** SQLite (Relational), ChromaDB (Vector).
*   **Authentication:** Google OAuth 2.0, python-jose (JWT).

---

## 💻 Installation & Setup

1. **Clone the repository.**
2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Start Ollama:**
   Ensure Ollama is installed and running on your machine with the required models.
   ```bash
   ollama pull llama3.2
   ollama pull nomic-embed-text
   ollama serve
   ```
4. **Configure Environment Variables:**
   Ensure your `.env` file is populated with your `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_SECRET`, and `ADMIN_EMAIL`.
5. **Run the Backend Server:**
   ```bash
   uvicorn main:app --reload
   ```
6. **Access the App:**
   Open `http://localhost:8000` in your browser.

---

## 👨‍💻 Usage Flow

1. **Admin Mode:** Log in with the designated `ADMIN_EMAIL`. Upload core curriculum PDFs (like textbooks or syllabi). These are flagged as `is_admin = True` and become the global baseline knowledge for all students.
2. **Student Mode:** Students log in, create a session, and can upload their own specific homework PDFs.
3. **Query:** When a student asks a question, the RAG pipeline fetches the top `k=40` chunks combining both their personal uploads and the Admin's global uploads, synthesizing a perfectly tailored, hallucination-free response.
4. **Cleanup:** Deleting a chat session from the UI safely drops the relational SQL records and triggers a metadata-targeted deletion in ChromaDB to instantly free up disk space and vector memory.
