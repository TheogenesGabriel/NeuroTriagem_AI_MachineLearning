# Interface do teste de trajetórias

A tela do joystick acompanha o protocolo 2 (`TRAJETORIAS_2D`) do projeto local
`NeuroTriagem_firmware_completo`. O firmware realiza, nesta ordem: calibração do
centro, quadrado, triângulo e círculo. O aplicativo somente recebe dados pela USB;
o botão A da placa inicia e o botão B interrompe para abrir o oxímetro.

## Cursor em tempo real

O firmware atualizado envia `JOYSTICK_POSICAO` durante o posicionamento e o percurso,
com intervalo mínimo de 50 ms (até 20 atualizações/s). O cursor verde acompanha os
eixos X/Y, o alvo azul acompanha o próximo ponto, e o caminho é desenhado enquanto
o joystick se move. Tempo e progresso vêm da placa, sem simulação no aplicativo.

Para ativar, grave `releases/NeuroTriagem_joystick_live.uf2` na BitDogLab: conecte-a
em modo BOOTSEL, copie o arquivo para a unidade `RPI-RP2`, aguarde reiniciar e
reabra o aplicativo. Se a porta mudar após a gravação, selecione a nova porta.
O código Python atualizado sozinho não consegue obter posições do firmware antigo.

Se a telemetria parar por mais de 1,5 s, a tela oculta o cursor ao vivo e indica
que está aguardando novos dados. O traçado recebido continua disponível.

## Uso

1. Execute o aplicativo com `.venv\Scripts\python.exe main.py` e avance até o joystick.
2. Confirme a porta serial e clique em **Conectar**. A porta usada na pré-triagem é
   reaproveitada; a conexão só é confirmada depois que a porta realmente abre.
3. Pressione A e solte o joystick durante a calibração.
4. Posicione no ponto inicial por 300 ms (prazo de 30 s), depois siga cada figura no
   sentido horário, no seu ritmo (até 90 s por percurso). Acompanhe sua posição e
   o próximo alvo na tela do computador ou no OLED da placa.
5. Confira os resultados recebidos por figura. **Concluir Triagem** fica disponível
   quando chega `JOYSTICK_FINAL`, inclusive quando há percursos parciais ou não iniciados.

As figuras da tela reproduzem os 48 alvos, o raio normalizado de 0,75 e a orientação
do firmware. O traçado de aproximação ao ponto inicial não é misturado ao percurso.
Ao trocar de fase, o relógio e o traçado recomeçam conforme os eventos da placa.
Os resultados finais substituem tempo e progresso provisórios da telemetria.

O firmware pode exportar coordenadas com `JOYSTICK_EXPORTAR_AMOSTRAS=ON`. Nesse caso,
a tela substitui a prévia de movimento pelo registro exportado **depois** do
percurso, quando recebe as linhas `JOYSTICK_AMOSTRA`. Essa opção é desligada por
padrão e não é necessária para o cursor ao vivo nem para mostrar as métricas.

O protocolo permanece na versão 2; a extensão é compatível com os leitores que
ignoram eventos desconhecidos. Exemplo de evento durante o percurso:

```text
JOYSTICK_POSICAO,forma=QUADRADO,fase=PERCURSO,t_ms=120,x=-0.50000,y=0.75000,alvo_x=-0.37500,alvo_y=0.75000,passo=3,progresso=4
```

O `JOYSTICK_INICIO` informa `telemetria_ms=50`. A telemetria não altera a aquisição
das métricas, que continua com período pretendido de 20 ms e timestamps reais.
O envio ao vivo não espera o computador consumir os dados: se a USB estiver
indisponível ou sem espaço para uma linha completa, o quadro visual é descartado.

## Resultados e limites

- `CONCLUIDO`: todos os alvos alcançados em ordem.
- `TEMPO_LIMITE`: percurso parcial, com métricas próprias desse registro.
- `NAO_INICIADO`: prazo de posicionamento esgotado, sem métricas válidas. A tela usa
  travessões em vez de apresentar os zeros do firmware como resultados medidos.
- `valido`: integridade numérica, independente de conclusão ou interpretação clínica.

Tempo, caminho, velocidade, aceleração, desvio, RMSE, sobreposição, NPV, número de
amostras e maior intervalo são preservados. NPV significa número de velocidades
acima da média; a área entre curvas não é calculada. As unidades de movimento são
normalizadas, sem conversão para força, milímetros ou graus.

O protocolo anterior de direções/força foi substituído. As métricas novas não são
convertidas em `joystick_falhou` nem incorporadas automaticamente ao Random Forest.
O modelo mantém suas features existentes. O protocolo e o processamento do oxímetro
permanecem inalterados.

Um novo `JOYSTICK_INICIO` limpa os resultados anteriores. Cancelar antes do fim
mantém apenas os registros parciais e não libera a conclusão. Cancelar após
`JOYSTICK_FINAL` preserva o resultado final, conforme o firmware. Erros de calibração
e conexão são exibidos; mensagens de outras etapas, como `OXI_*`, são ignoradas.

## Verificação

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_joystick*.py" -v
```

Os testes reproduzem o protocolo, fragmentos de leitura serial, entradas inválidas,
troca de sessão, sinais Qt entre threads, cursor/alvo ao vivo, perda de telemetria,
estados da interface e geometria das figuras. Não requerem placa conectada.
A confirmação física da porta, dos eixos e
da interação com os botões deve ser feita com a BitDogLab.
