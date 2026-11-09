# Joystick com cursor ao vivo

Arquivo: `NeuroTriagem_joystick_live.uf2`

Este firmware acrescenta o envio USB da posição e do próximo alvo durante o
posicionamento e o percurso. A interface Python atualizada usa esses dados para
mover o cursor verde, desenhar o rastro e atualizar tempo/progresso.

## Gravar e usar

1. Desconecte a porta serial no aplicativo.
2. Conecte a BitDogLab em modo BOOTSEL, mantendo o botão BOOTSEL do Pico pressionado
   enquanto conecta o cabo USB.
3. Copie `NeuroTriagem_joystick_live.uf2` para a unidade `RPI-RP2`.
4. Aguarde a placa reiniciar. Feche e abra novamente o aplicativo Python para
   carregar a interface atualizada.
5. Na tela do joystick, selecione a porta serial da placa e clique em **Conectar**.
   Pressione A, solte o joystick na calibração e siga o alvo azul.

O envio da posição ocorre durante as fases de posicionamento e percurso; o joystick
não movimenta o cursor da tela antes de iniciar o teste. O firmware anterior não
envia essas posições. O botão B continua interrompendo o teste para abrir o oxímetro.

## Build e verificação

- Raspberry Pi Pico SDK 1.5.1; ARM GCC 13.2 Rel1; alvo `pico`.
- 117.760 bytes.
- SHA256: `5BAA47CCFE3E43072F6C812C3C58C772F344CECF1756EED22C000EF16356E91A`.
- 54 testes Python aprovados; testes C de geometria/métricas e fluxo do firmware
  aprovados, incluindo envio USB sem leitor ou com buffer cheio.
- A gravação e o teste físico na placa ainda precisam ser realizados.

Os fontes foram atualizados no projeto vizinho `NeuroTriagem_firmware_completo`.
A pasta `.build/joystick_live/original_backup` guarda cópias dos arquivos substituídos.
