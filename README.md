# Relocation Brief Web App (v2)

This build matches your updated quiz logic:
- Step 1: City (Continue activates after input)
- Step 2: Household (solo/couple/family + children ages)
- Step 3: Housing (default Buy toggle to Rent; bedrooms; property type; dual-range budget slider)
- Step 4: Priorities (5 cards; pick at least one)
- Step 5: Work commute (optional: Yes/Skip; transport + slider + address)
- Step 6: School commute (optional: Yes/Skip; transport + slider)
- Final: Download PDF / Markdown + clarifying questions (optional)

## Run backend (Windows PowerShell)
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
notepad .env
uvicorn app:app --reload --port 8000
```

## Run frontend
```powershell
cd frontend
copy .env.local.example .env.local
npm install
npm run dev
```

Open http://localhost:3000
