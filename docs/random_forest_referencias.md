# Referências e relação com o Random Forest do projeto

Consulta realizada em 1 de novembro de 2026. As referências orientam escolhas de engenharia; elas não demonstram a validade de um classificador de risco neurológico com as variáveis deste projeto.

## 1. MAX30102, PPG e regressão de pressão arterial

Tjitra, M. A.; Anju, N. E.; Sudiana, D.; Rizkinia, M. **A Wireless Noninvasive Blood Pressure Measurement System Using MAX30102 and Random Forest Regressor for Photoplethysmography Signals**. *Computers*, 13(5), 125, 2024. [Artigo e DOI](https://doi.org/10.3390/computers13050125).

O estudo estima pressão sistólica e diastólica com Random Forest **Regressor**, usando amplitudes de quatro componentes da onda PPG: foot, notch, sistólico e diastólico. Descreve pré-processamento, extração de atributos, busca de hiperparâmetros e integração do modelo à interface. A coleta incluiu seis participantes e 114 medições antes da limpeza. A seção 3.1.3 relata R² de teste negativos: −1,08 e −2,13, apesar de erros absolutos médios relativamente baixos. Isso limita a interpretação de generalização.

**Aplicação aqui:** separar aquisição, atributos, treinamento, avaliação e inferência. **Não transferível:** os atributos PPG e os alvos de pressão não correspondem a BPM/SpO₂ resumidos nem a classes de risco neurológico. O artigo não justifica inferir pressão arterial a partir apenas dos campos atuais do aplicativo.

## 2. ECG portátil e classificação cardíaca

Nugraha, R. F. A. et al. **Portable ECG Prototype based on Arduino and Random Forest Classification for Home Heart-Rate Monitoring**. *AVITEC*, 7(3), 311–320, 2025. DOI: 10.28989/avitec.v7i3.3144. [PDF fornecido pelo usuário](https://pdfs.semanticscholar.org/2abe/2d06f2b718e92f4a2b2427442ff7fbc6041c.pdf).

O protótipo utiliza Arduino Uno e AD8232, registra CSV e analisa sinais em Jupyter. O texto distingue frequência normal, bradicardia e taquicardia. Na seção 2.4, descreve a implementação embarcada como uma estrutura de limiares e `if/else` que imita árvores; isso não equivale, por si, ao treinamento de uma floresta de árvores independentes com `RandomForestClassifier`. A avaliação relatada envolve 100 amostras em condições estáticas.

**Aplicação aqui:** fluxo reproduzível de aquisição, armazenamento, análise e integração. **Não transferível:** a acurácia cardíaca relatada não estima desempenho na triagem neurológica. Não criar rótulos de risco com limiares das mesmas entradas e apresentar o resultado como validação clínica.

## 3. Referência IEEE ainda não verificada

[IEEE Xplore, documento 11546535](https://ieeexplore.ieee.org/document/11546535).

Não foi possível recuperar o conteúdo ou metadados confiáveis nessa consulta. A página principal, a página de resumo e o acesso ao PDF falharam; a busca pelo identificador não localizou o artigo. Título, método, conjunto de dados e resultados **não foram presumidos**. A referência fica registrada para revisão quando houver acesso ao texto.

## Decisões metodológicas para este projeto

Estas são decisões da implementação, não resultados demonstrados pelos artigos:

- Usar classificação para um alvo categórico definido por anotação independente; as classes e seu significado precisam de protocolo próprio.
- Manter todas as sessões de uma pessoa na mesma partição, evitando que repetições da mesma pessoa apareçam no treino e no teste.
- Ajustar imputação e hiperparâmetros somente com dados de treinamento, mantendo o teste final separado.
- Comparar com uma referência simples e analisar matriz de confusão, recall por classe, balanced accuracy e F1 macro; acurácia isolada é insuficiente para avaliar classes desbalanceadas.
- Identificar dados sintéticos como demonstração de software. Eles não fornecem evidência de sensibilidade ou especificidade clínica.
- Manter o contrato de atributos igual no notebook e na aplicação; medidas ausentes não devem virar sinais normais por padrão.

Para fundamentar uso clínico, ainda será necessário definir o desfecho, coletar dados rotulados representativos e avaliar o sistema em participantes independentes. Os artigos consultados não fornecem uma base rotulada compatível com as entradas de braço, face, sinais vitais e joystick do NeuroTriagem.AI.
