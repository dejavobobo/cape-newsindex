# Examples

| File | What it is |
| --- | --- |
| [`run_epu.py`](run_epu.py) | The whole EPU run in a few lines: edit the settings at the top, run it, get the dashboard and Excel file. Start here. |
| [`test_with_drive.ipynb`](test_with_drive.ipynb) | The same as a notebook, for a real archive (a synced Google Drive folder, or Drive mounted in Colab). |
| [`sample_articles.xlsx`](sample_articles.xlsx) | 24 hand-labeled articles (2 countries x 2 newspapers x 2 months x 3 articles). Each `expected_is_epu` label is verified against the bundled keyword template; `note_for_reviewer` names the terms each article hits. |
| [`test_with_excel.ipynb`](test_with_excel.ipynb) | Runs `sample_articles.xlsx` step by step -- classification, counting, fitting a history period and scoring against it, group aggregation -- and checks every number against hand-computed values. Needs no other data. |
