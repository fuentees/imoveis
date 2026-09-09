# Deixar o bot rodando

## 1. Credenciais do Telegram

Para tarefa agendada, o mais simples é pôr o token no `config.yaml`
(ele está no `.gitignore`, não vai pro Git):

```yaml
telegram:
  token: "123456:ABC-DEF..."       # do @BotFather
  chat_id: "12345678"              # de @userinfobot
```

Teste antes de agendar:

```bash
python main.py --once --dry-run    # não envia, só imprime
python main.py --once              # envia de verdade um ciclo
```

## 2. Windows — Task Scheduler (recomendado)

Roda `run.bat` (= `main.py --once`) de tempos em tempos. Sobrevive a reboot.

1. **Iniciar → "Agendador de Tarefas" → Criar Tarefa** (não "Tarefa Básica").
2. **Geral:** nome `bot-imoveis`. Marque **"Executar estando o usuário
   conectado ou não"** e **"Executar com privilégios mais altos"**.
3. **Disparadores → Novo:** "Diariamente", repetir a cada **3 horas**,
   por "1 dia" (indefinidamente).
4. **Ações → Nova:**
   - Programa: `C:\Users\vfcarvalho\bot-garimpeiro-imoveis\run.bat`
   - Iniciar em: `C:\Users\vfcarvalho\bot-garimpeiro-imoveis`
5. **Condições:** desmarque "Iniciar a tarefa apenas se o computador
   estiver ligado na tomada" se for notebook.
6. OK (pede a senha do Windows).

Para conferir: aba **Histórico** da tarefa, e o `bot.log` na pasta do projeto.
O `intervalo_minutos` do `config.yaml` é ignorado nesse modo — quem agenda é
o Windows.

## 3. Alternativa — modo loop

```bash
python main.py --loop
```

Fica rodando e re-varre a cada `agendamento.intervalo_minutos`. Simples, mas
**para se o terminal fechar ou o PC reiniciar**. Para deixar 24/7 assim, use
uma máquina sempre ligada (Raspberry Pi, VPS, notebook velho) com `systemd`
ou `cron` chamando `python main.py --once`.

## 4. Primeira semana

- Rode em `--loop` ou agendado e **confira na mão** os alertas que chegam.
- Ajuste no `config.yaml`: `limiar_desconto`, `min_amostra`, `exigir_keyword`.
- Olhe o `bot.log` de vez em quando: linha `[!]` = site que quebrou
  (seletor desatualizado), `[robots]` = bloqueado por robots.txt.
