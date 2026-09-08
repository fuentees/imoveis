# 🏠 Bot Garimpeiro de Imóveis

Monitora sites de imobiliárias, agrupa anúncios comparáveis, calcula a **mediana
de preço/m² por grupo**, sinaliza os que estão muito abaixo e **cruza com
palavras-chave de espólio / venda urgente**. Manda os achados pelo **Telegram**.

## Como funciona (o raciocínio)

1. **Raspa** cada imobiliária configurada (um bloco por site no `config.yaml`).
2. **Agrupa comparáveis**: `cidade | bairro | tipo | faixa de metragem | faixa de quartos`.
   Comparar o m² da região inteira gera falso positivo — unidade grande "dilui"
   o m². Por isso a comparação é sempre dentro do grupo.
3. **Mediana de preço/m²** por grupo (só confia em grupos com amostra suficiente).
4. **Sinaliza** quem está X% abaixo da mediana do próprio grupo.
5. **Cruza com palavras-chave** (`espólio`, `inventário`, `urgente`, `aceito
   proposta`...). Esse é o sinal que separa oportunidade real de imóvel-problema.
6. **Pontua e alerta** no Telegram (sem repetir imóvel já enviado).

## Instalação

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml   # e edite
```

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
python3 main.py --once --dry-run      # roda uma vez, só imprime (calibração)
python3 main.py --once                # roda uma vez e envia pelo Telegram
python3 main.py --loop                # roda continuamente (intervalo do config)
python3 main.py --once --max-paginas 1  # teste rápido, 1 página por site
```

Para deixar rodando sozinho: use o `--loop`, ou agende o `--once` no `cron`.

## Calibração (importante)

- Comece com `exigir_keyword: false` e olhe o que aparece no `--dry-run`.
- Se vier muito ruído, suba o `limiar_desconto` (0.30 → 0.40) ou ligue
  `exigir_keyword: true` (só alerta barato QUE TAMBÉM tem palavra-chave).
- Ajuste a lista `PALAVRAS_CHAVE` em `analyzer.py` ao vocabulário da sua região.

## ⚠️ Ressalvas honestas

- **Preço de anúncio ≠ preço de venda.** A mediana é de anúncios (inflados). O
  "abaixo do m²" indica candidato a investigar, não desconto garantido. Ninguém
  compra no automático — o bot só encurta o funil.
- **Cada site é um site.** Layout muda → seletor quebra. Isso é manutenção
  esperada, não defeito.
- **Termos de uso.** Sites de imobiliária pequena costumam não ter anti-scraping,
  mas verifique o `robots.txt` e os termos de cada um. Mantenha o `delay` alto
  (seja educado) e não sobrecarregue os servidores.

## Estrutura

```
parser.py     extrai preço/área/quartos de texto BR ("R$ 1.250.000", "120 m²")
scraper.py    raspador genérico configurável por seletores CSS
analyzer.py   grupos + mediana de preço/m² + outlier + palavras-chave + score
storage.py    SQLite: histórico de imóveis + controle de já-alertados
notifier.py   envio pelo Telegram (Bot API)
main.py       orquestrador (--once / --loop / --dry-run)
config.yaml   sua configuração (sites, limiares, credenciais)
```
