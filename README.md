# Festőműhely asszisztens (Painting Studio Assistant)

MI-alapú festőtanár: egy festmény fotójából **mért képadatokra** (paletta, valőr, kompozíció)
épülő, strukturált kritikát ad, és **valós múzeumi mesterműveket** ajánl tanulási referenciaként.
Két modellel fut: **Gemini** (felhő) vagy **lokális modell** (Ollama) – a saját, nem publikus
művek csak a lokális modellhez kerülhetnek (kódban kikényszerítve).

Az alkalmazás nyelve **angol**: a felület, a modell válaszai (a rendszerprompt és a SKILL.md-k angol kimenetet kérnek),
a hibaüzenetek és a kód szövegei. A dokumentáció (`docs/`) magyar.

> Mesterséges intelligencia eszközök és alkalmazások (VEMIVIM333MA), Pannon Egyetem, 2026/27/1 – féléves projekt.

## Telepítés

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env            # majd írd be a GEMINI_API_KEY-t
.venv/bin/python scripts/fetch_samples.py   # közkincs tesztképek letöltése
```

**Gemini kulcs:** https://aistudio.google.com/apikey (ingyenes szint elég). Csak a `.env`-be kerül, gitbe nem.

> **Ingyenes keret:** **kb. 20 kérés/nap/modell** (a keret modellenként külön számít). Egy kritika ≈ 3 kérés
> (előszűrés + tool-hívás + végső JSON), egy referenciakeresés ≈ 4–6. Alapértelmezett modell: `gemini-3.5-flash`;
> ha elfogy, a felület a „Daily Gemini quota used up” üzenetet mutatja – válts az oldalsáv **Gemini model**
> legördülőjében pl. `gemini-3.5-flash-lite`-ra, vagy várj másnapig.

**Lokális modell (Ollama):**
```bash
brew install ollama
brew services start ollama        # háttérszolgáltatásként (vagy: ollama serve)
ollama pull qwen3-vl:8b-instruct  # alapértelmezett: látó + tool-hívó, gondolkodás nélkül (~6 GB)
ollama pull qwen3-vl:8b           # opcionális: „gondolkodó” változat, összehasonlításhoz
```
Futásidő (M5 Max): `8b-instruct` – kritika ~20 s, referenciák ~15–20 s; a „gondolkodó” `8b` – kritika ~80–100 s,
referenciák ~3 perc, érdemi minőségi előny nélkül. Erősebb gépen: `qwen3-vl:30b`. Ha egy modell nem tud tool-t hívni, a rendszer automatikusan
„fallback” módra vált (a kód futtatja az eszközöket, az eredményt promptban adja át).

## Futtatás

```bash
.venv/bin/streamlit run app.py
```

A felület: http://localhost:8501

```bash
.venv/bin/python -m pytest -q                              # egységtesztek (hálózat/LLM nélkül)
.venv/bin/python eval/run_eval.py --provider ollama --runs 3   # kiértékelés
.venv/bin/python eval/run_eval.py --provider gemini --runs 2 --images starry --no-references   # kvótabarát
```

## Felépítés

```
app.py                     Streamlit felület (angol nyelvű; Tabler ikonok, barátságos hibaüzenetek)
assets/icons/             Tabler Icons SVG-k (MIT licenc) – offline is működnek
.streamlit/config.toml    Streamlit beállítás (feltöltési korlát: 15 MB)
.cache/                   helyi adatok, gitből kizárva: results/ (mentett eredmények), paintings/ (saját festmények)
assistant/
  agent.py                 orchestrator: skill futtatás, tool-ciklus, önjavítás
  skills.py                SKILL.md betöltő (progressive disclosure)
  tools.py                 tool-regiszter (JSON séma + függvény, jogosultság-ellenőrzés)
  image_tools.py           paletta (k-means), valőrtanulmány, kompozíció – klasszikus képfeldolgozás
  museum.py                The Met + Art Institute of Chicago nyílt API
  guard.py                 biztonság: adatvédelem, injection-előszűrés, kimenet-ellenőrzés
  schemas.py               Pydantic kimeneti sémák
  llm/                     szolgáltató-független réteg: gemini_provider, ollama_provider
skills/
  painting-critique/SKILL.md
  reference-finder/SKILL.md
eval/run_eval.py           mérőszámok: sémakövetés, következetesség, injection, hallucináció
docs/                      dokumentáció, prezentációvázlat
```

Részletek: [docs/DOKUMENTACIO.md](docs/DOKUMENTACIO.md)
