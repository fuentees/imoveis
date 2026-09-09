# 🏠 Bot Garimpeiro de Imóveis

Monitora sites de imobiliárias, agrupa anúncios comparáveis, calcula a **mediana
de preço/m² por grupo**, sinaliza os que estão muito abaixo e **cruza com
palavras-chave de espólio / venda urgente**. Manda os achados pelo **Telegram**.

## Como funciona (o raciocínio)

1. **Raspa** cada imobiliária configurada (um bloco por site no `config.yaml`),
   respeitando o `robots.txt` de cada domínio.
2. **Agrupa por** `cidade | bairro | tipo`. Dentro do grupo, cada imóvel é
   comparado só com os **comparáveis** dele (área ±35% e quartos ±1) — janela
   relativa, sem o "efeito degrau" de faixas fixas.
3. **Mediana de preço/m²** dos comparáveis (só confia com amostra suficiente).
   A amostra junta a raspagem atual + o histórico recente do banco.
4. **Sinaliza** quem está X% abaixo da mediana dos próprios comparáveis.
5. **Cruza com palavras-chave** (`espólio`, `inventário`, `urgente`, `aceito
   proposta`...). Esse é o sinal que separa oportunidade real de imóvel-problema.
6. **Pontua e alerta** no Telegram (sem repetir imóvel já enviado; só re-alerta
   se o preço cair mais depois).

## Instalação

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml   # e edite
```

No Windows use `python` (não `python3`). Para rodar os testes:
`pip install -r requirements-dev.txt && pytest`.

## Configurar o Telegram

1. No Telegram, fale com **@BotFather** → `/newbot` → copie o **TOKEN**.
2. Mande qualquer mensagem pro seu bot.
3. Descubra seu **chat_id** em `https://api.telegram.org/bot<TOKEN>/getUpdates`
   (ou use **@userinfobot**).
4. Prefira variáveis de ambiente:
   ```bash
   export TELEGRAM_TOKEN="123:ABC..."
   export TELEGRAM_CHAT_ID="12345678"
   ```

## Configurar os sites

Cada imobiliária vira um bloco em `sites:` no `config.yaml`. Abra o site,
aperte **F12** (inspecionar), ache o "card" de cada anúncio na listagem e
preencha os seletores CSS. Os campos podem ficar vazios — o bot tenta extrair
do texto do card como fallback.

## Uso

```bash
python main.py --once --dry-run      # roda uma vez, só imprime (calibração)
python main.py --once                # roda uma vez e envia pelo Telegram
python main.py --loop                # roda continuamente (intervalo do config)
python main.py --once --max-paginas 1  # teste rápido, 1 página por site
```

Para deixar rodando sozinho (Task Scheduler no Windows, `--loop`, cron):
ver **[docs/rodando.md](docs/rodando.md)**. O log vai pro console e pra
`bot.log` (troque com `--log-file` ou `--log-file ""`).

## Calibração

Já calibrado para o litoral sul de SP a partir de dry-runs reais:

- `min_amostra: 6` — abaixo disso a mediana ficava instável em bairro de nicho
  (casas de 670 m², coberturas). Grupos menores não geram alerta de preço.
- **Palavra-chave só dispara sozinha se for "forte"** (espólio, inventário,
  herança…). `partilha`, `desocupado` e afins entram em `KEYWORDS_FRACAS`
  (`analyzer.py`) — aparecem em rodapé jurídico de site, então só contam quando
  o imóvel também está abaixo do mercado.
- Palavra-chave é ignorada se o imóvel está **acima** da mediana do grupo.
- `Paulumar` roda com `detalhe: true` — o card e a página divergiam na área.

Para apertar mais: suba `limiar_desconto` (0.30 → 0.40) ou ligue
`exigir_keyword: true`. Ajuste `PALAVRAS_CHAVE` ao vocabulário da sua região.

## O alerta no Telegram

Cada alerta diz, em texto claro: preço e specs, **quanto** está abaixo do
preço/m² típico (em % e em R$), **qual** a base de comparação (ex.: "casas de
208–432 m², 4–6 quartos, em Jardim Acapulco"), o **tamanho da amostra** e a
confiança, os sinais de venda encontrados, e o lembrete de que preço de anúncio
não é preço de venda.

## ⚠️ Ressalvas honestas

- **Preço de anúncio ≠ preço de venda.** A mediana é de anúncios (inflados). O
  "abaixo do m²" indica candidato a investigar, não desconto garantido. Ninguém
  compra no automático — o bot só encurta o funil.
- **Cada site é um site.** Layout muda → seletor quebra. Isso é manutenção
  esperada, não defeito.
- **Termos de uso.** O bot já checa o `robots.txt` de cada domínio, mas leia
  também os termos de uso. Mantenha o `delay` alto (seja educado) e não
  sobrecarregue os servidores.

## Estrutura

```
parser.py     extrai preço/área/quartos de texto BR ("R$ 1,2 milhão", "120 m²")
scraper.py    raspador genérico configurável por seletores CSS (+ robots.txt)
analyzer.py   grupos + comparáveis (área/quartos) + mediana + keywords + score
storage.py    SQLite: histórico de imóveis + já-alertados (com preço do alerta)
notifier.py   envio pelo Telegram (Bot API)
log.py        logging pro console e pro bot.log
main.py       orquestrador (--once / --loop / --dry-run)
config.yaml   sua configuração (sites, limiares, credenciais)
tests/        pytest (parser, analyzer, scraper, storage)
```
