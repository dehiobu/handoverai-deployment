# GP Triage AI - Proof of Concept

A RAG-based AI system for GP triage using Streamlit, LangChain, ChromaDB, and OpenAI.

## 🎯 Overview

This POC demonstrates an AI-powered triage system that:
- Analyzes patient symptoms in natural language
- Retrieves similar validated cases
- Provides RED/AMBER/GREEN triage decisions
- Shows clinical reasoning and red flags
- References NICE guidelines

## 📋 Prerequisites

- Python 3.10 or higher
- OpenAI API key
- AI-validated dataset (447 cases)

## 🚀 Quick Start

### 1. Setup Environment

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Mac/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
# Copy environment template
copy .env.example .env    # Windows
cp .env.example .env      # Mac/Linux

# Edit .env and add your OpenAI API key
# OPENAI_API_KEY=sk-your-key-here
```

### 3. Prepare Training Data

```bash
# Copy your AI-validated dataset
copy path\to\ai_validated_dataset_TEMPORARY.json data\ai_validated_dataset.json
```

### 4. Initialize Vector Store

```bash
# Run setup script (first time only)
python scripts/setup_vectorstore.py
```

This will:
- Load 447 training cases
- Generate embeddings
- Create ChromaDB vector store
- Takes 5-10 minutes

### 5. Run Application

```bash
# Start Streamlit app
streamlit run app.py
```

Browser opens automatically at: `http://localhost:8501`

## 📁 Project Structure

```
gp-triage-poc/
├── app.py                      # Main Streamlit application
├── config.py                   # Configuration settings
├── requirements.txt            # Python dependencies
├── .env                        # Environment variables (create from .env.example)
│
├── src/
│   ├── __init__.py
│   ├── vector_store.py        # ChromaDB management
│   └── rag_pipeline.py        # RAG logic and prompting
│
├── scripts/
│   └── setup_vectorstore.py   # Vector store initialization
│
├── data/
│   └── ai_validated_dataset.json  # Training cases (you provide)
│
├── chroma_db/                 # Vector database (auto-created)
└── logs/                      # Application logs (auto-created)
```

## 🎮 Usage

### Basic Workflow

1. **Enter patient description** in natural language
2. **Click "Triage Patient"** button
3. **Review results:**
   - Triage decision (RED/AMBER/GREEN)
   - Urgency timeframe
   - Clinical reasoning
   - Red flags
   - NICE guidelines
   - Recommended action

### Example Inputs

**RED (Emergency):**
```
64-year-old male
Crushing chest pain started 40 mins ago
Pain radiating down left arm
Sweating profusely
Nauseous
```

**AMBER (Urgent):**
```
35-year-old female
Persistent cough for 3 weeks
Some blood in sputum yesterday
Losing weight unintentionally
Night sweats
```

**GREEN (Routine):**
```
28-year-old male
Runny nose for 2 days
Mild sore throat
No fever
Otherwise well
```

## ⚙️ Configuration

### Environment Variables

Edit `.env` file:

```bash
# OpenAI API Key (required)
OPENAI_API_KEY=sk-your-key-here

# Model Configuration
EMBEDDING_MODEL=text-embedding-3-small
CHAT_MODEL=gpt-4o
TEMPERATURE=0.0
MAX_TOKENS=1000

# Logging
LOG_LEVEL=INFO
```

### Customization

Edit `config.py` to change:
- Number of similar cases retrieved (SIMILARITY_TOP_K)
- Model parameters
- File paths
- Triage levels

## 🧪 Testing

### Manual Testing

Test with various scenarios:
- Emergency cases (cardiac, stroke, anaphylaxis)
- Urgent cases (infections, injuries)
- Routine cases (minor illnesses)
- Edge cases (vague symptoms, multiple conditions)

### Check Accuracy

Compare AI decisions with:
- Your clinical judgment
- Similar cases in training data
- NICE guidelines

## 💰 Costs

- **Infrastructure:** £0 (runs locally)
- **OpenAI API:** ~£0.05 per triage
- **Monthly (testing):** ~£5-10 (100-200 triages)

## ⚠️ Limitations

**This is a POC (Proof of Concept):**

- ❌ Not for clinical use
- ❌ Not validated by real GPs yet
- ❌ Not suitable for production
- ❌ Single user only
- ❌ No data persistence
- ❌ No authentication

**Use only for:**
- ✅ Testing and demonstration
- ✅ Proof of concept validation
- ✅ Internal demos
- ✅ Fundraising presentations

## 🔄 Troubleshooting

### Vector Store Issues

```bash
# Delete and recreate vector store
rm -rf chroma_db/
python scripts/setup_vectorstore.py
```

### OpenAI API Errors

- Check API key in `.env`
- Verify API quota/billing
- Check internet connection

### Slow Performance

- First query is slower (loading models)
- Subsequent queries faster (cached)
- Consider using fewer similar cases (reduce SIMILARITY_TOP_K)

### Module Not Found

```bash
# Reinstall dependencies
pip install -r requirements.txt --upgrade
```

## 📊 Next Steps

### Before Production

1. **GP Validation:** Get 2 GPs to validate 447 cases
2. **Dataset Swap:** Replace AI-validated with GP-validated data
3. **Funding:** Apply for SBRI/Innovate UK grants
4. **AWS Migration:** Deploy to AWS for scalability
5. **Regulatory:** Ensure MHRA/CQC compliance

### Migration to AWS

When ready to scale:
- Follow `AWS_SAAS_ARCHITECTURE.md` guide
- 95% code reuse
- 2-3 days migration time
- Production-ready SaaS

## 📚 Documentation

- **SIMPLE_PYTHON_STACK.md** - Complete technical guide
- **AWS_SAAS_ARCHITECTURE.md** - Production deployment guide
- **config.py** - Configuration options
- **requirements.txt** - Dependencies

## 🐛 Known Issues

- ChromaDB may show warnings (can be ignored)
- First startup takes 30-60 seconds
- Large datasets (>1000 cases) may be slow

## 🆘 Support

Issues? Check:
1. All dependencies installed
2. OpenAI API key set
3. Dataset file in `data/` folder
4. Virtual environment activated

## 📝 License

This is a proof of concept. Not licensed for production use.

## 👤 Author

Dennis Ehiobu  
AI Innovation Specialist & Senior Technical Business Analyst  
Sutatscode Ltd

---

## 🎉 Quick Command Reference

```bash
# Setup
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env with your OpenAI key

# Initialize
python scripts/setup_vectorstore.py

# Run
streamlit run app.py

# Reinstall
pip install -r requirements.txt --upgrade

# Clean
rm -rf chroma_db/ logs/
```

---

**Built with:** Streamlit • LangChain • ChromaDB • OpenAI GPT-4o  
**Status:** POC - AI Validated (GP validation pending)  
**Version:** 0.1.0
