# Homologação HTTP isolada — passada 10

Este smoke é uma prova limitada de fronteira HTTP WSGI, não uma implantação nem
uma validação pública. Ele roda exclusivamente no worker autorizado, em um cliente
descartável com rede Docker `none`, PostgreSQL descartável `cbn_test_*` por socket
UNIX e request HTTP sobre o loopback interno do próprio cliente. Não usa banco ou
backup real, nem segredo, token, identidade ou dado pessoal real.

## Checklist reproduzível no CI03

1. Partir do SHA commitado e da allowlist revisada; o dispatcher `tools/ci_worker.py`
   recusa árvore suja ou divergente da allowlist.
2. Despachar uma única execução autorizada ao CI03 com o lock compartilhado; não
   executar esta integração no control plane e não concorrer com outro worker.
3. O worker existente cria o banco descartável exclusivo, preserva os containers
   anteriores e executa as regressões já definidas antes de `homolog_cases.py`.
4. O caso cria `create_app(...)` com IDs sintéticos fornecidos em runtime, inicia
   apenas o harness `wsgiref` temporário e confirma health mínimo e erro de autenticação
   sanitizado por HTTP real.
5. Confirmar no relatório do worker `homolog_http=PASS`, a remoção do container
   descartável e a preservação dos containers preexistentes. A evidência operacional
   permanece privada.

## Fronteiras fail-closed

O harness aceita apenas bind de loopback e porta efêmera; qualquer outro endereço é
rejeitado antes de abrir listener. O handler não escreve log de request, header,
corpo, credencial ou PII. `/healthz` retorna somente estado estático e os demais
caminhos delegam à aplicação já configurada. Ao sair, o servidor é encerrado e os
pools da aplicação são fechados.

`wsgiref` é usado somente neste smoke descartável e não é servidor de produção.
Ele não publica rota, DNS, proxy, TLS, firewall ou URL de Android. O cliente Android
continua sem URL local ou privada configurada como destino final.

## Gates restantes

Este arquivo não satisfaz G-DEPLOY. HTTPS público, backup persistente/restore,
segredos de runtime, observabilidade operacional, rollback e aceite em 4G/5G exigem
G-DEPLOY e as aprovações dependentes. G-PRIVACY, G-OIDC, G-SOURCES e G-TTS continuam
necessários antes de qualquer identidade, dado, fonte ou síntese real.
