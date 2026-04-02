# GP TRIAGE POC - INSTALLATION GUIDE
# Step-by-Step Setup Instructions

## ✅ CHECKLIST

Before you start, ensure you have:
- [ ] Python 3.10+ installed
- [ ] OpenAI API key ready
- [ ] AI-validated dataset file (ai_validated_dataset_TEMPORARY.json)
- [ ] 30 minutes of time
- [ ] Internet connection

---

## 📦 STEP 1: EXTRACT FILES

1. Download the complete `gp-triage-poc.zip` file
2. Extract to your preferred location (e.g., `C:\Projects\gp-triage-poc`)
3. Open terminal/command prompt in this directory

---

## 🐍 STEP 2: SETUP PYTHON ENVIRONMENT

### Windows:

```cmd
# Navigate to project
cd C:\Projects\gp-triage-poc

# Create virtual environment
python -m venv venv

# Activate virtual environment
venv\Scripts\activate

# You should see (venv) in your prompt
```

### Mac/Linux:

```bash
# Navigate to project
cd /path/to/gp-triage-poc

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# You should see (venv) in your prompt
```

---

## 📥 STEP 3: INSTALL DEPENDENCIES

```bash
# With virtual environment activated
pip install -r requirements.txt

# This will install:
# - Streamlit (web interface)
# - LangChain (RAG framework)
# - ChromaDB (vector database)
# - OpenAI (LLM API)
# - And other dependencies

# Takes 2-5 minutes
```

**Expected output:**
```
Successfully installed streamlit-1.29.0 langchain-0.1.0 ...
```

---

## 🔑 STEP 4: CONFIGURE OPENAI API KEY

### Option A: Using .env file (Recommended)

```bash
# Windows
copy .env.example .env
notepad .env

# Mac/Linux
cp .env.example .env
nano .env
```

Edit the `.env` file:
```
OPENAI_API_KEY=sk-your-actual-api-key-here
```

Save and close.

### Option B: Using environment variable

**Windows:**
```cmd
set OPENAI_API_KEY=sk-your-actual-api-key-here
```

**Mac/Linux:**
```bash
export OPENAI_API_KEY=sk-your-actual-api-key-here
```

---

## 📂 STEP 5: PREPARE TRAINING DATA

1. **Locate your AI-validated dataset:**
   - File: `ai_validated_dataset_TEMPORARY.json`
   - Generated from: `python ai_temporary_validation.py`

2. **Copy to data directory:**

**Windows:**
```cmd
copy C:\Projects\GPTriage\ai_validated_dataset_TEMPORARY.json data\ai_validated_dataset.json
```

**Mac/Linux:**
```bash
cp /path/to/ai_validated_dataset_TEMPORARY.json data/ai_validated_dataset.json
```

3. **Verify file exists:**
```bash
# Windows
dir data\ai_validated_dataset.json

# Mac/Linux
ls -lh data/ai_validated_dataset.json
```

You should see the file (approx 2-5 MB).

---

## 🗄️ STEP 6: INITIALIZE VECTOR STORE

This step creates the vector database from your training cases.

```bash
# Run setup script
python scripts/setup_vectorstore.py
```

**What happens:**
```
======================================================================
GP TRIAGE - VECTOR STORE SETUP
======================================================================

[INFO] Loading training data from:
   C:\Projects\gp-triage-poc\data\ai_validated_dataset.json

[INFO] Vector store already exists!
   Delete and recreate? (yes/no):
   [INFO] Clearing existing Chroma data...
   [OK] Existing vector store cleared

Creating vector store...
(This may take a few minutes for 447 cases)

Loading cases from C:\Projects\gp-triage-poc\data\ai_validated_dataset.json...
Found 447 cases
Creating vector embeddings... (this may take a few minutes)
✓ Vector store initialized!

======================================================================
[SUCCESS] Vector store created successfully!
======================================================================

[PATH] Location: chroma_db/

[NEXT] Next steps:
   1. Run: streamlit run app.py
   2. Open browser to: http://localhost:8501
   3. Start triaging!
```

**Duration:** 5-10 minutes (creating embeddings for 447 cases)

**Troubleshooting:**
- Ignore `Failed to send telemetry event...` warnings; they are harmless.
- If it fails, check your OpenAI API key and ensure billing is enabled.
- Ensure the dataset file exists in `data/`.
- Close any running `streamlit run app.py` sessions before answering “yes”.
- Check internet connection.

---

## 🚀 STEP 7: RUN THE APPLICATION

```bash
# Start Streamlit app
streamlit run app.py
```

**Expected output:**
```
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://192.168.1.x:8501
```

Browser opens automatically! 🎉

---

## ✅ STEP 8: TEST THE SYSTEM

1. **Enter a test case:**
   ```
   64-year-old male
   Crushing chest pain for 40 minutes
   Pain going down left arm
   Sweating and nauseous
   ```

2. **Click "Triage Patient"**

3. **Review result:**
   - Should show: **RED (Emergency)**
   - Urgency: **999 now**
   - Clinical reasoning displayed
   - Red flags identified

4. **Try more cases:**
   - Use the example templates
   - Test different severities
   - Verify results make sense

---

## 📊 VERIFICATION CHECKLIST

After installation, verify:

- [ ] Streamlit app opens in browser
- [ ] No error messages in terminal
- [ ] Test case triages correctly
- [ ] RED/AMBER/GREEN decisions shown
- [ ] Clinical reasoning displayed
- [ ] History section works
- [ ] Response time < 10 seconds

---

## 🔄 DAILY USAGE

After initial setup, to run the app:

```bash
# 1. Navigate to project
cd C:\Projects\gp-triage-poc

# 2. Activate environment
venv\Scripts\activate          # Windows
source venv/bin/activate       # Mac/Linux

# 3. Run app
streamlit run app.py

# 4. Browser opens automatically
```

**To stop:** Press `Ctrl+C` in terminal

---

## 🐛 TROUBLESHOOTING

### Problem: "ModuleNotFoundError"

**Solution:**
```bash
# Ensure virtual environment is activated
# (you should see (venv) in prompt)

# Reinstall dependencies
pip install -r requirements.txt
```

### Problem: "OpenAI API key not found"

**Solution:**
```bash
# Check .env file exists and contains key
cat .env  # Mac/Linux
type .env # Windows

# Or set environment variable
export OPENAI_API_KEY=sk-...  # Mac/Linux
set OPENAI_API_KEY=sk-...     # Windows
```

### Problem: "Training data not found"

**Solution:**
```bash
# Verify file exists
ls data/ai_validated_dataset.json

# If missing, copy from original location
cp path/to/ai_validated_dataset_TEMPORARY.json data/ai_validated_dataset.json
```

### Problem: Vector store errors or folder locked

**Solution:**
1. Stop any running Streamlit instance (`Ctrl+C` in the terminal where it’s running).
2. Re-run the setup script and answer **yes** when prompted:
   ```bash
   python scripts/setup_vectorstore.py
   ```
3. The script now resets Chroma safely—no manual delete needed.

### Problem: Slow performance

**Causes:**
- First query is always slower (loading models)
- Subsequent queries are faster
- Normal: 5-10 seconds per triage

**If consistently slow:**
- Check internet connection
- Reduce SIMILARITY_TOP_K in config.py
- Restart the app

---

## 💰 COST TRACKING

Monitor your OpenAI usage:
1. Visit: https://platform.openai.com/usage
2. Check API usage
3. Expected: ~£0.05 per triage

**Typical costs:**
- Development/testing: £5-10/month
- Heavy testing (200 cases): ~£10/month

---

## 🎯 NEXT STEPS

Now that it's working:

1. **Test thoroughly**
   - Try 20-30 different cases
   - Test edge cases
   - Verify accuracy

2. **Demo to stakeholders**
   - Show to colleagues
   - Get feedback
   - Refine as needed

3. **Plan GP validation**
   - Recruit 2 GPs
   - Prepare cases for validation
   - Budget £1,600-2,000

4. **Prepare for funding**
   - Document results
   - Create pitch deck
   - Apply for SBRI grants

---

## 📞 SUPPORT

**Common Issues:**
- Check README.md for detailed docs
- Review config.py for customization
- Check logs/ directory for error logs

**Still stuck?**
1. Check Python version: `python --version` (need 3.10+)
2. Check pip version: `pip --version`
3. Verify OpenAI API key at: platform.openai.com
4. Try fresh installation in new directory

---

## ✅ SUCCESS INDICATORS

You know it's working when:
- ✅ App loads without errors
- ✅ Test cases triage correctly
- ✅ Response time < 10 seconds
- ✅ Clinical reasoning makes sense
- ✅ History section populates
- ✅ No errors in terminal

---

## 🎉 CONGRATULATIONS!

Your GP Triage POC is now running!

**What you've accomplished:**
- ✅ Complete RAG-based triage system
- ✅ 447 AI-validated training cases
- ✅ Professional web interface
- ✅ Ready for demos and testing

**Total setup time:** ~30 minutes  
**Cost so far:** £18 (AI validation)  
**Value:** Production-ready POC! 💪

---

## 📚 FURTHER READING

- **README.md** - Full documentation
- **SIMPLE_PYTHON_STACK.md** - Technical architecture
- **AWS_SAAS_ARCHITECTURE.md** - Production deployment
- **config.py** - Configuration options

---

**Ready to build your SaaS? Let's go! 🚀**
