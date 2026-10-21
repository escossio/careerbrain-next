# CI independente e workers dedicados

Workflow foundation: PR para main e despacho manual, permissões contents: read,
actions por SHA, checkout sem credenciais persistidas, dependências por hash,
Python 3.13 e timeouts curtos. Jobs obrigatórios: contracts e repository-policy.
Sem secrets, banco, deploy, cache ou artefatos privados; pull_request_target não é usado.
Instalação baixa dependências; os testes seguintes bloqueiam rede e subprocessos.
Política de publicação inspeciona arquivos revisados e blobs do novo histórico.

Worker-readiness é somente manual; requer NEXT_WORKERS_APPROVED=true antes de
agendar runner self-hosted/linux/x64/careerbrain-next. Não certifica banco ou pool.
Workers futuros: efêmeros, identidade/checkout mínimos, namespace por SHA/run,
sem acesso a serviços/segredos/produção de outros projetos. Limpeza só dos recursos
criados pelo job; sem prune e sem contornar locks compartilhados. Ausência de
capacidade bloqueia o gate, sem teste pesado no control plane ou runner hosted.
Nenhum runner é instalado/configurado pela preparação do candidato.

## Proteção pretendida da main

PR obrigatório; checks contracts e repository-policy vinculados ao GitHub Actions,
branch atualizada, conversas resolvidas e histórico linear. Force-push e deleção
bloqueados; administradores sujeitos às regras e sem bypass configurado.
Com um mantenedor: required_approving_review_count=0, require_code_owner_reviews=false
e require_last_push_approval=false. CODEOWNERS declara responsabilidade sem criar
aprovação de terceiro. Confirmar tudo pela API após autorização; ainda não aplicado.
Não fazer merge automaticamente. Mudanças no quadro de mantenedores exigem revisão.
