# Vaga lógica, publicação e confiança V1

Payload `publish` exige `source_id`, ID estável da vaga na origem, título,
organização, descrição útil (mínimo técnico de 80 caracteres, não prova semântica),
requisitos quando fornecidos, modalidade/local/tipo (`unknown` explícito permitido),
canal oficial e evento comprovado. Campos mandatórios ausentes não são inferidos.
O produtor enriquece; o núcleo não coleta portal, CSV ou links para corrigir dados.

Identidades externas: `(source_id, source_vacancy_id)` e `(source_id,
source_event_id)`. `vacancy_id` e `publication_event_id` internos são atribuídos pelo
backend. O catálogo guarda relações entre fontes, sem fusão automática por título
ou hash aproximado. Mesma evidência de publicação em produtores distintos mapeia
para o mesmo evento. Possível duplicata entre fontes exige prova de equivalência;
sem prova, não se promete deduplicação perfeita e não se fundem vagas distintas.

`event.published_at` é SEMPRE o instante efetivo daquele evento, original ou
republicação. Originais e republicações preservam histórico; republicação exige
evento anterior da mesma vaga já resolvido, instante estritamente posterior e
evidência independente da mera edição. Não há outro `republished_at` concorrente.
Falta de prova rejeita o novo evento; a publicação original permanece intacta.
Nenhum evento aceito pode ter data alterada in-place. Correção temporal exige
retirada do evento incorreto e nova publicação comprovada, com trilha de auditoria.

Timestamps de publicação/observação não podem ser futuros em relação ao recebimento;
observação >= publicação. Sem fallback para ingestão, updated_at ou data do celular.
Elegibilidade: evento ativo com `event.published_at >= account_created_at`, usando
instantes UTC. Igualdade é elegível. Novo currículo, score ou conteúdo não muda isso.

## Evidência e direitos

`authorization_id` referencia registro operacional previamente aprovado que vincula
produtor, fonte, direitos de uso/exibição e contatos oficiais. `evidence_id`, digest
SHA-256, tipo, URL, observação e versão do extrator permitem verificar publicação.
A referência deve existir em repositório de evidências aprovado; um hash/url
autodeclarado não autentica a origem. Testes usam registro sintético em memória.
Provas reais/licenças são gate externo, sem alegação de verificação automática.

URL: HTTPS pública, sem usuário/senha, fragmento, endereço privado/loopback ou
parâmetros de autenticação. E-mail oficial só é aceito se estiver no registro
aprovado da fonte. Validação sintática não certifica existência/autoridade do canal.
API não faz fetch de URLs de payload. Verificação de origem é responsabilidade
governada do produtor; qualquer futuro fetch terá controles SSRF próprios.

## Lifecycle

`correct`: revisão identificada por origem, patch explícito e evidência; muda versão
de conteúdo, sem alterar identidade/data. `close` e `withdraw`: desativam evento,
invalidam projeções e geram remoção na sincronização. Replay da mesma revisão é
idempotente; mesmo ID de revisão com conteúdo diferente é conflito. Republicação
é `publish` com kind `republication`, referência anterior e prova, nunca `correct`.
Reabertura requer novo evento comprovado. Não se revive evento retirado.
