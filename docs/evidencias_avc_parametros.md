# Evidências sobre os parâmetros atuais e AVC

Pesquisa realizada em **1 de novembro de 2026**, para orientar o desenvolvimento do NeuroTriagem.AI. O objetivo investigado é reconhecer suspeita de AVC agudo; isso difere de prever um AVC futuro ou estimar o prognóstico depois de um AVC confirmado.

**Conclusão para o treinamento:** as fontes sustentam investigar alterações súbitas de face e braço como sinais de alerta. Elas não fornecem rótulos individuais para as cinco entradas do projeto nem validam uma regra que transforme BPM, SpO₂ ou `arm_ratio` em diagnóstico de AVC. Treinar uma floresta para reproduzir regras criadas a partir dessas faixas mede reprodução da regra, não detecção de AVC.

## Evidência e correspondência com o código

| Parâmetro | O que a fonte estabelece | Como interpretar no projeto |
| --- | --- | --- |
| Face | Assimetria ao sorrir é um sinal de alerta no B.E. F.A.S.T.; o NIHSS avalia movimentos e pontua paresia facial de 0 a 3. | A saída YOLO `facial_asymmetry_score` de 0 a 2 não é NIHSS, probabilidade de AVC nem diagnóstico. Precisa de comparação com avaliação independente. |
| Braço | Fraqueza ou queda de um braço ao elevar ambos é um sinal de alerta no B.E. F.A.S.T. No NIHSS, testa-se cada braço por 10 segundos, a 90° sentado ou 45° deitado; o item motor vai de 0 a 4. | `arm_ratio` é uma grandeza geométrica própria, sem conversão clínica estabelecida nas fontes consultadas. O lado 1/2 identifica lateralidade, não gravidade. |
| Frequência cardíaca | A AHA apresenta 60–100 BPM como faixa usual de repouso; frequência elevada também aparece em estudos de risco futuro e de prognóstico. | BPM permanece como variável contextual contínua. Nenhuma dessas referências torna um valor isolado um teste positivo ou negativo para AVC agudo. |
| SpO₂ | A FDA informa 95–100% para a maioria das pessoas saudáveis. O NICE usa saturação abaixo de 95% no contexto de suporte de oxigênio a pessoas com AVC. | O corte de 95% é de manejo nesse contexto, não de diagnóstico. Não gerar `AVC=1` por SpO₂ baixa ou `AVC=0` por SpO₂ normal. |

Fontes dos sinais de alerta: [American Stroke Association — B.E. F.A.S.T.](https://www.stroke.org/en/about-stroke/stroke-symptoms). Fonte dos procedimentos e escores: [NINDS — NIH Stroke Scale](https://www.ninds.nih.gov/sites/default/files/migrate-documents/nih_stroke_scale_booklet_508c.pdf). Faixas vitais: [AHA — All About Heart Rate](https://www.heart.org/en/health-topics/high-blood-pressure/the-facts-about-high-blood-pressure/all-about-heart-rate-pulse) e [FDA — Pulse Oximeter Basics](https://www.fda.gov/consumers/consumer-updates/pulse-oximeter-basics). Contexto de suporte: [NICE NG128, recomendação 1.5.1](https://www.nice.org.uk/guidance/NG128/chapter/recommendations#maintenance-or-restoration-of-homeostasis).

## Reconhecimento e confirmação são etapas diferentes

O NICE recomenda uma ferramenta validada, como FAST, no reconhecimento extra-hospitalar de sintomas neurológicos de início súbito; também orienta excluir hipoglicemia e fazer avaliação diagnóstica rápida e neuroimagem conforme o contexto. O aplicativo atual não contém toda essa avaliação: sua classificação de face e braço não inclui, por exemplo, um registro estruturado de início súbito nem o componente de fala. Portanto, não deve ser apresentado como uma aplicação validada do FAST ou do NIHSS. [NICE NG128, seções 1.1 e 1.3](https://www.nice.org.uk/guidance/NG128/chapter/recommendations).

No código atual, `ARM_TEST_DURATION_S` vale 20 segundos por padrão e `ARM_DRIFT_RATIO_THRESHOLD` vale 0,6; `arm_ratio` divide a diferença vertical suavizada entre punhos pela largura dos ombros. Esses são parâmetros de engenharia do projeto. As fontes consultadas não estabelecem 0,6 como corte de AVC. Reduzir o temporizador para 10 segundos, por si só, tampouco transformaria esse teste em NIHSS: posição, instruções, execução por membro, critérios de pontuação e avaliação do observador também fazem parte do procedimento.

## BPM: prognóstico não é detecção de um evento atual

Um estudo com **8.031 pacientes que já tinham AVC isquêmico** analisou frequências cardíacas entre o quarto e o sétimo dia após o início. Identificou cortes de **81 BPM para a média** e **100 BPM para o máximo** associados ao desfecho composto de recorrência, infarto ou morte em um ano, com validação em outra coorte. Esses números não foram obtidos para separar pessoas com e sem AVC na triagem inicial; não devem ser usados para fabricar esse alvo no treinamento. [Estudo original — Effect of Heart Rate on 1-Year Outcome for Patients With Acute Ischemic Stroke](https://pmc.ncbi.nlm.nih.gov/articles/PMC9238577/).

Além disso, em uma coorte de 129.135 mulheres após a menopausa, a frequência de repouso não apresentou associação independente com AVC após os ajustes do estudo. A interpretação depende de população, fatores associados e desfecho. Isso reforça a necessidade de avaliar BPM dentro de uma base compatível, em vez de fixar uma associação universal. [Estudo original — Women’s Health Initiative, BMJ](https://www.bmj.com/content/338/bmj.b219).

O valor médio de BPM também não equivale à presença de fibrilação atrial. O NICE recomenda verificar pulso irregular quando há suspeita e confirmar o diagnóstico de fibrilação atrial por ECG de 12 derivações. Manter ECG para uma etapa futura não permite substituir essa informação por `heart_rate > 100`. [NICE NG196, seção 1.1](https://www.nice.org.uk/guidance/NG196/chapter/recommendations#detection-and-diagnosis).

## SpO₂ e qualidade da medição

O oxímetro estima saturação periférica. A FDA descreve limitações de precisão, inclusive relacionadas a pigmentação da pele e condições de medição. O treinamento precisa registrar leituras ausentes ou inadequadas e analisar desempenho por subgrupos e dispositivos. O fato de uma leitura estar entre 95% e 100% não fornece, nas referências acima, um critério de exclusão de AVC. [FDA — Pulse Oximeter Basics](https://www.fda.gov/consumers/consumer-updates/pulse-oximeter-basics).

## Consequências para a base e para a avaliação

1. O alvo deve ser obtido por uma referência independente, por exemplo o diagnóstico final documentado segundo um protocolo previamente definido, incluindo casos com suspeita inicial e diagnósticos alternativos.
2. A base deve medir as mesmas entradas da implantação. Um escore NIHSS ou uma coluna genérica de fraqueza não substitui automaticamente `arm_ratio` ou a saída específica do YOLO.
3. Não criar valores de braço/face que faltam em uma base pública usando o próprio diagnóstico; isso revela o alvo às entradas. Não inferir o diagnóstico usando cortes dos mesmos atributos e reportar a acurácia como clínica.
4. Manter dados sintéticos, quando usados, identificados como simulação. Suas métricas descrevem apenas o experimento artificial.
5. Usar pacientes separados entre treino e teste, reportar sensibilidade e especificidade, valores preditivos na prevalência relevante, matriz de confusão e calibração. Planejar validação externa e avaliação de condições que imitam AVC.

Essas escolhas de modelagem são conclusões de engenharia a partir das diferenças entre os dados do projeto e os procedimentos/fontes descritos. A pesquisa não estabelece validade clínica para o classificador atual.

## Nota de acesso às fontes

Os trechos oficiais das páginas NICE e do PDF NINDS foram recuperados pelo índice de busca; algumas tentativas de abrir as páginas diretamente retornaram HTTP 403. Isso foi tratado como limitação de acesso, sem presumir conteúdo adicional. O resumo/trechos do estudo de frequência cardíaca foram recuperados pela página do artigo indexada. As referências são específicas aos fatos descritos, não substituem leitura integral para desenho de um protocolo clínico.
