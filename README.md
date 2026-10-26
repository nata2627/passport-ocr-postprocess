# Постобработка OCR паспорта РФ

По выводу OCR-модели решает, принять паспорт (и выдать значения 10 полей) или отклонить и попросить переснять. Принятый документ с ошибкой дороже отклоненного, поэтому решение настроено на ноль ошибок.

- `postprocess.py` точка входа
- `src/mrz.py` разбор MRZ, контрольные цифры, транслитерация МВД, восстановление строки одной правкой
- `src/pipeline.py` проверки полей и решение accept/reject
- `src/resources.py` словари по разметке train и справочнику подразделений
- `model/resources.json` собранные словари, нужны для работы без интернета
- `answers.jsonl` ответы на test
- [REPORT.md](REPORT.md) отчет и прогноз

## Запуск

Python 3.9+, только стандартная библиотека, CPU, без интернета. Данные задания положить в `data/` (справочник подразделений уже лежит в `reference/`).

```
python postprocess.py data/test_predictions.jsonl answers.jsonl
python postprocess.py data/test_predictions.jsonl answers.jsonl --no-grace   # без 90-дневного окна после 20 и 45 лет
python scripts/build_resources.py   # пересобрать словари по data/train_labels.jsonl
python scripts/cv.py -v             # 5-кратная кросс-валидация на train
python -m pytest tests
python scripts/plots.py             # графики для отчета
```

На test принимается 1008 документов из 2000, прогноз ошибок около 8 (подробно в отчете).
