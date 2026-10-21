# Sincronização, candidaturas e TTS V1

`GET /v1/recommendations/changes?cursor=...&limit=...`, 1–100 itens, default 50.
Log por usuário usa sequence crescente **na conclusão/commit de disponibilização**
da recomendação ou remoção, não no published_at/relógio do cliente. Publicação
continua definindo elegibilidade. Classificação tardia ganha sequence nova e não
se perde se o cliente já avançou o cursor.

Primeira página fixa high-watermark; páginas seguintes só incluem sequence <=
esse marco e > posição anterior. Cursor opaco autenticado vincula usuário, geração
do feed, marco e posição; não permite escolher outro tenant. Itens ordenados por
sequence; feed de novidades é distinto do ranking por relevância da listagem.
Novo evento durante paginação fica para ciclo seguinte. Persistir next_cursor no
aparelho só após aplicar/deduplicar página localmente. Retry devolve mesmos IDs;
sem promessa de exactly-once de transporte, sem perder novidades. Leitura tem ACK
explícito; fetch não marca lido. Estado lido no servidor permite múltiplos devices.
Reinstalação faz bootstrap completo da projeção vigente elegível, sem depender de
cursor armazenado no app. Cursor expira após 30 dias → 410 CURSOR_EXPIRED e
bootstrap paginado completo, preservando estados e corte temporal. Nunca retorna
sucesso vazio para cursor inválido. Eventos descartados viram REMOVED no feed.

`GET /v1/recommendations` lista a projeção atual elegível, em ranking estável por
afinidade/novidade/ID dentro de snapshot do perfil/política. Seu cursor é distinto
do feed de mudanças; empate tem ID como desempate. Página 1–100, default 50;
perfil/política alterados invalidam snapshot e pedem nova paginação. Toda página
revalida conta/owner e remove eventos encerrados/retirados, mesmo em snapshot antigo.
A resposta nunca exibe match `eligible=false`.

## Candidaturas

Estado manual por `(user_id, publication_event_id)`, versões otimistas e request_id.
Estados: SAVED, APPLIED, INTERVIEW, OFFER, REJECTED, WITHDRAWN. O usuário pode corrigir
para qualquer estado conhecido; expected_version divergente → 409 sem sobrescrever.
Replay de request_id igual é idempotente, conteúdo distinto é conflito. Republicação
começa sem estado; API pode exibir referência ao histórico anterior sem herdar uma
candidatura automaticamente. Sem envio de candidatura ou monitor Gmail.

## TTS

App solicita resumo por notification_id e template permitido NEW_MATCHES/HIGH_AFFINITY,
count e pt-BR; não envia texto livre, currículo, nome do usuário ou perfil ao TTS.
Backend resolve owner e pendências; template produz no máximo 240 caracteres.
Contratos internos existentes `text/profile/language` ficam atrás do adaptador.
Não aceitar profile/provider arbitrário no app. Resposta áudio MPEG tem acesso
privado, sem URL pública permanente; cache por owner/evento, TTL máximo 15 minutos,
expurgo na exclusão. Preferir streaming sem arquivo durável. Uma fala consolidada
ao abrir, mediante gesto/controle do áudio; sem push obrigatório ou backlog falado.

Gateway planejado tem identidade exclusiva Next, allowlist de síntese/perfil/idioma,
timeout de 5s, concorrência 1, sem retry automático de síntese ambígua. Sucesso ou
falha não altera cursor nem marca leitura. G-TTS inclui orçamento/autorização de
síntese e retenção do provedor existente, separados do limite OpenAI. Sem caminho
seguro que preserve os demais serviços, integração real fica BLOQUEADA; fake offline permanece.
