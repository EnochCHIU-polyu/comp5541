# Data Directory

This directory stores all datasets used by the framework.

---

## Structure

```
data/
├── benchmarks/
│   ├── smartbugs/     # SmartBugs Curated benchmark (cloned from GitHub)
│   └── solidifi/      # SolidiFI injected-bug benchmark (cloned from GitHub)
├── vulnerable_contracts/   # Known-vulnerable .sol / .json files
└── synthetic_contracts/    # Auto-generated synthetic contracts (created at runtime)
```

---

## Setup: Download Benchmark Datasets

Both datasets are registered as **git submodules**. After cloning the outer repository, initialise them with:

```bash
git submodule update --init --recursive
```

After that, verify the datasets load correctly:

```bash
python main.py download-benchmarks --dataset all
```

If you need to add the submodules manually (e.g. in a fresh checkout without the `.gitmodules` file):

```bash
git submodule add https://github.com/smartbugs/smartbugs-curated.git data/benchmarks/smartbugs
git submodule add https://github.com/smartbugs/SolidiFI-benchmark data/benchmarks/solidifi
```

---

## Synthetic Contracts

Synthetic contracts are generated at runtime via:

```bash
python main.py generate-synthetic --num-vulns 2
```

Output is saved to `data/synthetic_contracts/`.

---

## PDF to Markdown Pipeline

You can convert a user-provided PDF into markdown and store it directly in this folder.

From project root:

```bash
.venv/bin/python run_pdf_to_md.py --pdf /path/to/file.pdf
```

Optional flags:

```bash
.venv/bin/python run_pdf_to_md.py \
	--pdf /path/to/file.pdf \
	--name custom_name.md \
	--output-dir data \
	--overwrite
```

The output markdown file will be saved under `data/`.

Implementation files:

- `phase1_data_pipeline/pdf_to_markdown.py`
- `scripts/pdf_to_md.py`
- `run_pdf_to_md.py`

---

## Notes

- `data/benchmarks/` is excluded from version control (listed in `.gitignore`).
- Parsed datasets are cached as `contracts.json` inside each benchmark subdirectory to avoid re-parsing on subsequent runs.
