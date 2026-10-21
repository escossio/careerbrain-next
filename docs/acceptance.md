# Aceite verificável por camada

Na 01: schemas válidos, referências locais resolvidas sem rede, exemplos positivos,
rejeições adversariais, limites e incompatibilidades detectados; políticas de repo
e workflows, nenhum conteúdo sensível versionado. O harness não prova autenticação
criptográfica, RLS, transação SQL, concorrência distribuída ou integração real.

Na 02: banco descartável nos workers; papel de runtime real; negação leitura/escrita
cross-tenant e sem contexto, reset de pool, constraints temporais e unicidade,
rollback compatível, backup/restore e reaplicação de exclusões. Sem dados reais.

Na 03: token RS256 assinado com chave sintética; rejeição de assinatura/issuer/
audience/presenter/nonce/tempo inválidos; desafio único e expirado; conta/tenant
estáveis sob login repetido e concorrente; papéis SQL reais; rotação, replay,
logout e exclusão revogam sessões; API nega token e escopo inválidos. PostgreSQL
descartável e jobs sem rede provam o caminho offline. Configuração OAuth real exige
os IDs públicos aprovados; jornada Google verdadeira permanece no aceite da 10.

Na 04: atomicidade SQL, retries concorrentes, conflito de chave, crash antes/depois
do commit e outbox transacional; produtor não pode escolher outro produtor/source.

Na 05/06/07: corpus sintético multissetorial (saúde, manutenção, serviços e TI),
fatos/requisitos ancorados em trechos, inferências rotuladas, saída inválida rejeitada,
prompt injection tratado como texto. Antes de benchmark pago, registrar conjunto,
rubrica e limiar de aprovação com base em risco e evidências. Zero exigência
obrigatória sem suporte é gate do corpus; não é garantia universal de acerto do modelo.
Nenhum percentual de throughput/baixa afinidade é fixado nesta fundação.

Na 06: cancelamento, expiração, reinício, disco cheio, parser interrompido,
duas gerações simultâneas, exclusão durante processamento, ausência do bruto em
DB/fila/DLQ/cache/log/backups e preservação do último perfil válido.

Na 08: classificação concluída após avanço do cursor; retry após perda de resposta;
mesma sequence em múltiplos devices; novos eventos durante paginação; exclusão
concorrente e restauração; catálogo preservado. Primeiro plano não confirma leitura.

Na 09: APK construído, testes instrumentados com API/IA/TTS fakes, retomada,
reinstalação controlada, offline, expiração e assinatura externa quando autorizada.
Na 10: Google verdadeiro, HTTPS público, 4G/5G e jornada integrada, incluindo TTS
real autorizado e exclusão. Fixtures sintéticas só em ambiente de teste segregado.
