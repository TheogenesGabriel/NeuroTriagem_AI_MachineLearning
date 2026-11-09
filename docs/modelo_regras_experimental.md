# Ficha do Random Forest experimental por regras

Entrega verificada em 2 de novembro de 2026. **Tarefa: imitar regras em cenários sintéticos. Não é um detector validado de AVC.**

## Artefato e reprodução

- Modelo: [`artifacts/random_forest_regras_experimental.joblib`](../artifacts/random_forest_regras_experimental.joblib).
- Notebook executado: [`notebooks/random_forest_neurotriagem.ipynb`](../notebooks/random_forest_neurotriagem.ipynb).
- Gerador e regras: [`core/random_forest_rules.py`](../core/random_forest_rules.py), versão 1.0, semente 42.
- Relatório: [`random_forest_regras_experimental_relatorio.json`](../artifacts/random_forest_regras_experimental_relatorio.json).
- Casos próximos dos limites: [`random_forest_regras_experimental_limites.json`](../artifacts/random_forest_regras_experimental_limites.json).

O notebook preserva o pipeline avaliado, sem reajustá-lo com os dados de teste. O artefato contém `data_kind=synthetic`, `learning_task=rule_imitation`, `label_provenance=synthetic_rules` e `diagnostic_performance_estimated=false`. A pedido do usuário, uma cópia foi incluída em `models/random_forest_regras_experimental.joblib` e ligada ao modo de demonstração do aplicativo por `core/random_forest_runtime.py`. O notebook e esse modo usam `allow_demo=True` explicitamente. O carregador genérico continua bloqueando dados sintéticos. Não foi criado um candidato real em `models/random_forest_risco.joblib`.

A interface identifica o modo experimental, apresenta medições ausentes e compara a previsão com a regra de referência. Divergências são informadas sem substituir a saída da floresta. O modelo e os resultados de treinamento abaixo permanecem os mesmos; esta integração não acrescenta validação clínica.

O botão **Ver classificação final** abre agora uma tela própria do NeuroTriagem.AI, com a previsão em destaque, quatro cartões de medições e o resumo descritivo do joystick. A inferência ocorre uma vez por avaliação e o resultado permanece preservado. Ausências e divergências aparecem na própria tela; o modo do modelo e a referência estão em **Detalhes da classificação**. É possível voltar ao início ou começar uma **Nova avaliação**, que limpa o resumo anterior.

O teste facial agora tem início manual, reinício e duração padrão de 20 segundos, ajustável de 5 a 60 na tela. Seu atributo é o maior grau observado na janela inteira, preservado ao concluir; antes da conclusão ou sem observação válida, fica ausente. As categorias do detector aparecem como Normal, Atenção — assimetria leve e Alerta — assimetria alta. São exibidas separadamente da previsão da floresta, que continua agrupando graus 1 e 2 na mesma regra motora. A janela móvel de frames serve somente à prévia. Essa mudança na aquisição não retreina o artefato sintético nem estende as métricas abaixo a vídeos; futuras bases reais precisam adotar o mesmo protocolo de aquisição.

## Dados e ajuste

Foram geradas 1.500 avaliações de 750 participantes fictícios, duas por participante, com 300 avaliações em cada uma das cinco classes. O gerador cobre combinações de regras e ausências; não estima prevalência ou correlações fisiológicas. Não foram usados casos clínicos, diagnósticos extraídos da internet ou rótulos AVC/sem AVC.

As entradas são `arm_ratio`, `arm_weak_side_code`, `facial_asymmetry_score`, `heart_rate` e `spo2`. BPM faz parte do modelo; ECG não é exigido. Os rótulos `DEMO_*` identificam regra motora, regra vital, ambas, nenhuma acionada ou dados incompletos. “Nenhuma regra acionada” não exclui AVC.

A divisão reservou 300 avaliações de 150 grupos fictícios para teste. As outras 1.200 avaliações de 600 grupos foram usadas em busca de oito configurações, com validação cruzada em três folds. Nenhum grupo aparece nos dois subconjuntos. A imputação foi ajustada dentro do pipeline de cada fold.

Configuração escolhida pela balanced accuracy na validação cruzada: 200 árvores, profundidade máxima 12, pelo menos duas amostras por folha, `max_features=sqrt` e `class_weight=balanced`.

## Resultados de fidelidade às regras

| Avaliação | Resultado |
|---|---:|
| Balanced accuracy média na validação cruzada | 97,08% |
| Concordância no teste reservado | 97,00% — 291 de 300 |
| Balanced accuracy no teste | 97,00% |
| F1 macro no teste | 0,9699 |
| Concordância do classificador de classe mais frequente | 20,00% |
| Concordância nos cenários de fronteira | 54,07% — 292 de 540 |
| Divergências nos cenários de fronteira | 248 de 540 |

O último conjunto é uma grade deliberada perto dos limites 0,6, 60/100 BPM e 95%, não uma amostra de uma população. Foi inspecionado depois do ajuste, sem usar seus resultados para retreinar ou escolher outros parâmetros. Ele mostra uma limitação relevante que a acurácia do teste aleatório esconde.

Por exemplo, para `[0.2, 0, 0, 59.99, 94.99]`, a regra retorna `DEMO_FAIXA_VITAL`, mas o modelo retorna `DEMO_SEM_REGRA_ACIONADA`. A floresta não reproduz exatamente os limiares. Também houve erros em quatro dos 60 casos incompletos do teste aleatório. Não se deve interpretar sua saída como ausência de sinal ou certeza clínica.

Como o alvo é calculado das próprias entradas, a função determinística de regras tem concordância perfeita por construção. Se o objetivo for apenas executar essas regras, essa função é a referência exata; não há ganho demonstrado em substituí-la pela floresta. O modelo serve para estudar treino, avaliação e integração. Um detector de AVC exigirá outro experimento, com desfecho clínico independente e validação representativa.

## Proveniência dos limiares

O valor 0,6 e as classes motoras/faciais vêm do código existente, não de pontos de corte clínicos validados. As faixas vitais são referências contextuais. As fontes e suas diferenças em relação ao projeto estão em [evidencias_avc_parametros.md](evidencias_avc_parametros.md); as bases analisadas estão em [bases_avc_avaliadas.md](bases_avc_avaliadas.md). Escores NIHSS não foram convertidos em saídas YOLO, nem médias de estudos foram transformadas em pacientes fictícios com suposto diagnóstico.

## Ambiente e verificação

Python 3.11.9; scikit-learn 1.9.1; NumPy 2.4.6; joblib 1.6.0; Matplotlib 3.11.2. A execução do notebook terminou sem erros, exportação e recarregamento preservaram as probabilidades. Após incluir o teste facial cronometrado e a tela de classificação final, a suíte do projeto passou em 149 testes. Os estados da interface e a integração com o artefato instalado foram conferidos sem webcam ou placa conectadas, incluindo dados incompletos, divergências, janela menor e nova avaliação. As alterações de Markdown do notebook preservaram suas células de código e saídas do treino anterior.

Hash SHA-256 da base normalizada e dos vetores de rótulos/grupos usado pelo notebook: `7132d0ee4536de4361e377d74b46b34c878a30ee87d593e1eccf5e5d22bb318c`.
