# Random Forest no NeuroTriagem.AI

O [notebook](notebooks/random_forest_neurotriagem.ipynb) treina, avalia e exporta um classificador compatível com o aplicativo. O detector facial já possui classes de normalidade e assimetria. Como ainda não existe uma base das cinco medições associadas a desfechos clínicos independentes, o Random Forest inicia em **modo de demonstração com dados sintéticos**. Suas métricas verificam a reprodução das regras do protótipo; não estimam risco de AVC nem desempenho clínico.

Os batimentos cardíacos (BPM) já são utilizados nesta versão, junto de SpO₂, braço e face. Apenas o ECG fica para uma etapa futura: não é uma entrada obrigatória nem é simulado a partir de BPM. Sua inclusão exigirá extração própria de atributos, atualização do contrato e novo treinamento.

## Modelo já integrado ao aplicativo

O protótipo treinado foi instalado em `models/random_forest_regras_experimental.joblib`. Para abrir o projeto com ele:

```powershell
.\.venv\Scripts\python.exe main.py
```

A tela inicial e a etapa final identificam **demonstração experimental com dados sintéticos**. Ao concluir o fluxo, o aplicativo executa a floresta com as cinco medições, apresenta rótulos legíveis, informa medidas ausentes e compara a previsão com a regra de referência. Se houver divergência, ela é mostrada; a previsão não é substituída silenciosamente. Não é exibida uma porcentagem como risco clínico.

Depois de receber o fim do teste do joystick, clique em **Ver classificação final**. O aplicativo abre uma tela própria do **NeuroTriagem.AI**, com a classificação em destaque, cartões de face, braço, BPM e SpO₂ e o resumo descritivo das trajetórias. O resultado permanece aberto e preserva uma cópia das medições daquela avaliação. Ausências e divergências ficam visíveis; **Detalhes da classificação** expande o modo do modelo e a regra de referência. **Nova avaliação** limpa o resumo e abre a pré-triagem; **Voltar ao início** retorna à tela inicial. A antiga janela de mensagem final foi substituída por essa tela.

Os títulos finais traduzem as cinco classes já treinadas: **Sinais motores e vitais**, **Sinal motor**, **Faixa vital sinalizada**, **Nenhuma regra acionada** e **Dados incompletos**. Uma falha de inferência aparece como **Classificação indisponível**. Esses títulos não criam novos níveis de risco clínico nem alteram o treinamento.

`core/random_forest_runtime.py` libera explicitamente esse artefato de demonstração e verifica versão, classes e configuração das regras. Se futuramente existir `models/random_forest_risco.joblib`, o candidato de dados reais tem prioridade; um candidato inválido permanece indisponível, sem troca silenciosa para demonstração. `RiscoRandomForest()` continua rejeitando artefatos sintéticos sem `allow_demo=True`.

O modelo incluído exige scikit-learn 1.9.1, versão fixada nos arquivos de dependências. O notebook é necessário apenas para novos experimentos, não para abrir o app. Executáveis antigos em `releases/` não foram reconstruídos: execute `main.py` para usar esta integração.

## Teste facial com tempo definido

Na tela facial, escolha a **duração de 5 a 60 segundos** (padrão: **20 segundos**) e clique em **Iniciar teste**. A câmera pode mostrar uma prévia antes disso, mas essas imagens não entram no resultado. **Reiniciar teste** descarta a captura anterior e começa uma nova janela desde zero. A tela mostra o tempo restante e preserva o resultado ao concluir.

| Grau do detector | Categoria apresentada no protótipo |
|---|---|
| 0 | Normal |
| 1 | Atenção — assimetria leve |
| 2 | Alerta — assimetria alta |

O resultado facial é o **maior grau reconhecido durante toda a janela**, e também aparece separado da previsão do Random Forest no resumo final. Se não houver detecção válida, o resultado fica ausente; isso não vira “Normal”. Uma observação isolada de grau alto pode determinar o máximo: a janela de 20 segundos e essa agregação são escolhas de engenharia para o protótipo, não um protocolo clínico validado. `FACE_VOTE_WINDOW` afeta apenas a prévia, não o resultado da sessão.

Essas categorias reconhecem os rótulos já existentes do detector. No Random Forest atual, os graus 1 e 2 acionam a mesma regra motora; as cinco classes `DEMO_*` continuam sendo as classes treinadas. “Alerta” indica assimetria alta observada, sem atribuir uma probabilidade de AVC.

O teste de braço já entra no modelo por `arm_ratio` e `arm_weak_side_code`. Ele pode fazer parte de uma futura avaliação clínica, comparando suas medidas com a avaliação independente do profissional e, para estudar detecção de AVC, com o desfecho clínico correspondente. A fraqueza de braço e a assimetria facial estão entre os sinais do [B.E. F.A.S.T. da American Stroke Association](https://www.stroke.org/en/about-stroke/stroke-symptoms); isso motiva investigá-las, mas não valida automaticamente os detectores deste aplicativo.

## Executar no Windows

Na raiz do projeto, use o ambiente `.venv` existente:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-notebooks.txt
.\.venv\Scripts\python.exe -m jupyterlab notebooks/random_forest_neurotriagem.ipynb
```

Execute as células em ordem, ou use **Run → Run All Cells**. O notebook e o aplicativo devem usar a mesma versão de `scikit-learn`. O arquivo `requirements-notebooks.txt` instala as dependências de análise; para executar toda a interface, também são necessárias as dependências de `requirements.txt`.

Com `MODO_DEMONSTRACAO = True`, o notebook cria 1.500 avaliações de 750 participantes fictícios e treina a floresta para imitar regras explícitas. O artefato gerado é `artifacts/random_forest_regras_experimental.joblib`; a cópia instalada no aplicativo fica em `models/`. O carregador genérico rejeita artefatos sintéticos sem liberação explícita. Não é necessário conectar sensores ou câmera para executar o notebook. O arquivo anterior `random_forest_demo.joblib`, caso presente, pertence ao primeiro exemplo com classes arbitrárias.

## Pesquisa e treinamento experimental por regras

A [pesquisa dos parâmetros](docs/evidencias_avc_parametros.md) e a [avaliação de bases públicas](docs/bases_avc_avaliadas.md) registram fontes e limitações. Como não foi localizada uma base aberta diretamente compatível, foi escolhido o protótipo sintético. A [ficha do modelo treinado](docs/modelo_regras_experimental.md) resume o resultado: **97% de concordância no teste aleatório e 54,07% nos casos próximos dos limites**. Esses valores não estimam detecção de AVC.

As regras estão em `core/random_forest_rules.py`. A condição motora usa `arm_ratio > 0.6`, lado indicado ou grau facial maior que zero. O corte 0,6 é um parâmetro de engenharia do projeto, sem validação clínica. A condição vital usa BPM fora de 60–100 ou SpO₂ abaixo de 95; são referências de contexto, não critérios de AVC. A ausência de qualquer entrada produz a classe técnica de dados incompletos, sem significar ausência de sinais.

| Classe sintética | Significado no simulador |
|---|---|
| `DEMO_SINAL_MOTOR` | Somente a regra motora acionada |
| `DEMO_FAIXA_VITAL` | Somente a regra vital acionada |
| `DEMO_MOTOR_E_VITAL` | Ambas acionadas |
| `DEMO_SEM_REGRA_ACIONADA` | Nenhuma acionada; não exclui AVC |
| `DEMO_DADOS_INCOMPLETOS` | Uma ou mais medidas ausentes |

Os rótulos vêm das próprias entradas; as métricas medem fidelidade a essas regras. A função determinística é a referência exata por construção, enquanto a floresta é uma aproximação. O notebook salva cenários fictícios em CSV, relatório, gráficos e divergências de fronteira em `artifacts/random_forest_regras_experimental_*`. As proporções de classes e distribuições não representam uma população clínica. O ECG continua fora das entradas.

## Preparar a base real

Use [data/random_forest_template.csv](data/random_forest_template.csv) como cabeçalho. Ele está vazio de propósito. Salve as observações em `data/neurotriagem_rotulada.csv`, com uma linha por avaliação, separador vírgula, codificação UTF-8 e ponto decimal:

```csv
patient_id,arm_ratio,arm_weak_side_code,facial_asymmetry_score,heart_rate,spo2,risco
```

| Coluna | Significado e formato |
| --- | --- |
| `patient_id` | Identificador pseudônimo estável da pessoa. Repita o mesmo ID em suas diferentes avaliações; não use nome, CPF ou outro identificador direto. É usado para separar treino e teste, e **não entra como atributo do modelo**. |
| `arm_ratio` | Razão de assimetria calculada pelo teste de braço, numérica e não negativa. O app guarda o valor no instante de conclusão do teste; não substitui esse resultado por posições adotadas depois. Ausente se não houver resultado. |
| `arm_weak_side_code` | Lado indicado pelo teste de braço: `0` = nenhum, `1` = esquerdo, `2` = direito. Usa o mesmo resultado congelado ao concluir o teste. Ausência de avaliação não significa `0`. |
| `facial_asymmetry_score` | Maior classe reconhecida durante o teste facial cronometrado: `0` = normal, `1` = leve/atenção, `2` = alta/alerta. Duração padrão de 20 segundos, ajustável de 5 a 60 na tela. Resultado congelado ao concluir; fica ausente antes da conclusão ou sem observação válida. |
| `heart_rate` | Frequência cardíaca em BPM. Célula vazia significa não medida; o valor legado `0` também é convertido em ausência. Valores negativos são rejeitados. |
| `spo2` | Saturação em porcentagem, entre `0` e `100`. Célula vazia ou o valor legado `0` significa não medida. |
| `risco` | Em uma base real, rótulo de referência definido por protocolo independente das saídas do sistema. Não pode estar vazio. As categorias clínicas e seus critérios ainda precisam ser definidos; não reutilize `DEMO_*` ou `CLASSE_DEMO_*` como categorias clínicas. |

Os cinco atributos de entrada são os campos entre `arm_ratio` e `spo2`. O joystick continua no fluxo da interface, mas suas medidas não entram nesta primeira versão do modelo. Não renomeie outras grandezas para preencher esses campos: a extração da base de treino deve corresponder à extração feita no aplicativo.

A coleta facial passou da janela móvel de frames para o máximo do intervalo cronometrado. Ao preparar uma base real, registre duração e protocolo de aquisição e mantenha-os consistentes entre treino e uso. Dados antigos com outra agregação não são automaticamente equivalentes. O modelo sintético existente não foi retreinado: ele recebe os mesmos códigos 0/1/2 e suas métricas continuam restritas aos cenários sintéticos originais.

Nas medidas, deixe células vazias para ausências. O treino rejeita registros sem nenhuma medição, colunas inteiramente ausentes e duplicatas exatas da mesma pessoa e rótulo. `patient_id` e `risco` são obrigatórios. Nenhuma rotina cria rótulos clínicos automaticamente.

## Treinar e interpretar os resultados

Para usar o protótipo atual, mantenha `MODO_DEMONSTRACAO = True`; não é necessário treinar novamente para abrir o aplicativo. **Somente quando houver a base real correspondente**, altere `MODO_DEMONSTRACAO = False`, confira `DATASET_PATH` e descreva a origem e o significado dos rótulos. Reinicie o kernel e execute tudo novamente.

O treinamento usa o pipeline compartilhado em `core/random_forest_model.py`: validação de atributos, imputação pela mediana com indicadores de ausência e `RandomForestClassifier`. A imputação é ajustada dentro de cada partição de treinamento.

A divisão reserva aproximadamente 20% dos dados para teste e mantém todas as observações da mesma pessoa na mesma partição. Nos aproximadamente 80% restantes, uma busca de hiperparâmetros usa validação cruzada em três partições, também agrupadas por pessoa, selecionando pela **balanced accuracy**. Não há mistura do teste final nessa seleção. A configuração exige suporte suficiente de pacientes por classe; o código interrompe o treino se uma partição ficar sem classes ou observações necessárias.

O relatório compara o Random Forest com `DummyClassifier`, apresenta matriz de confusão, recall/sensibilidade e especificidade por classe, F1 macro, balanced accuracy, ROC-AUC e average precision. A importância por permutação ajuda a inspecionar o comportamento do modelo; não demonstra causalidade. Não use o teste reservado repetidamente para escolher novas variáveis ou parâmetros. Cada linha tem o mesmo peso nas métricas, portanto pessoas com mais avaliações contribuem mais.

Os relatórios e gráficos PNG ficam em `artifacts/`. Para dados reais, o modelo candidato é exportado como `artifacts/random_forest_candidato.joblib`. O arquivo contém o pipeline, a ordem dos atributos e metadados de procedência e versão. Probabilidades do classificador não são probabilidades clínicas calibradas.

## Ativar um candidato no aplicativo

A configuração começa com `ATIVAR_NO_APP = False`. Depois de treinar e revisar um candidato com dados reais, altere para `True` e execute o notebook para salvar `models/random_forest_risco.joblib`. A proteção da célula impede ativar a demonstração sintética e recusa substituir um modelo já existente; preserve e mova a versão anterior antes de uma troca deliberada.

Reinicie o aplicativo para carregar o arquivo. Ao concluir o joystick, `RiscoRandomForest` é executado uma vez e o resultado é encaminhado à tela final. Sem modelo compatível, o resultado permanece indefinido; com um candidato real, a interface exibe o resultado acompanhado do aviso de classificação experimental. Ativar um modelo não o torna clinicamente validado.

Carregue somente arquivos `joblib` produzidos por você ou por fonte confiável: desserializá-los pode executar código. Se a versão do `scikit-learn` diferir entre treino e aplicação, use o mesmo ambiente ou treine/exporte novamente.

## Compartilhar e consultar as referências

Mantenha a base real e seus identificadores fora do controle de versão. A configuração de exclusões inclui os CSVs de dados, os artefatos e os candidatos de modelos, preservando o cabeçalho de exemplo e o modelo sintético explicitamente incluído em `models/`. Isso não remove dados já registrados anteriormente nem o conteúdo salvo dentro de um notebook.

Antes de publicar um notebook executado com dados reais, revise as células e limpe suas saídas:

```powershell
.\.venv\Scripts\python.exe -m jupyter nbconvert --clear-output --inplace notebooks/random_forest_neurotriagem.ipynb
```

Os artigos fornecidos e suas limitações estão em [docs/random_forest_referencias.md](docs/random_forest_referencias.md). O texto IEEE não pôde ser recuperado nesta consulta; seu conteúdo não foi presumido. As referências consultadas orientam o fluxo técnico, mas não fornecem uma base rotulada compatível nem validam a classificação neurológica deste projeto.
