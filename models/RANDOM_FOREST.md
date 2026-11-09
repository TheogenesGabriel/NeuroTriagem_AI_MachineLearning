# Modelo experimental incluído

`random_forest_regras_experimental.joblib` é a cópia do pipeline treinado em cenários sintéticos por regras. Inclui BPM, SpO₂ e atributos de braço/face; não requer ECG.

A aplicação carrega esse arquivo explicitamente em modo demonstrativo através de `core/random_forest_runtime.py`. Ele não representa diagnóstico nem probabilidade de AVC. A ficha, métricas e limitações estão em [docs/modelo_regras_experimental.md](../docs/modelo_regras_experimental.md).

Use scikit-learn 1.9.1, como fixado em `requirements.txt`. A biblioteca recusa versões incompatíveis. O arquivo deve permanecer com seus metadados de dados sintéticos; não o renomeie como `random_forest_risco.joblib`.

Para atualizar o protótipo após um novo experimento, revise o relatório do notebook e copie o artefato de `artifacts/` para este mesmo nome demonstrativo. Reinicie o aplicativo. A configuração de regras e suas classes precisam corresponder ao módulo `core/random_forest_rules.py`.
