# Identidade V1 — execução 03

A API WSGI implementa `/v1/auth/challenges`, `/v1/auth/google`,
`/v1/auth/refresh`, `/v1/auth/logout` e `GET /v1/me`. Outros endpoints do
OpenAPI pertencem a passadas posteriores. `create_app` exige IDs OAuth públicos
explicitamente aprovados e conexões separadas nos papéis `cb_auth` e `cb_api`;
falha na ausência deles. Não há client secret, chave Google privada nem banco
produtivo neste repositório.

O verificador usa PyJWT/cryptography, RS256 e chave obtida exclusivamente do
endpoint público fixo do Google. Valida assinatura, `kid`, `iss`, `aud`, `azp`,
`sub`, `iat`, `exp` e `nonce`; rejeita cabeçalhos que indiquem outra fonte de chave.
O desafio de 256 bits dura cinco minutos, seu digest fica no banco e o consumo é
atômico com provisionamento e emissão. Testes usam RSA e identidades inventadas,
com chave pública injetada; não representam login Google real.

Access e refresh são opacos e têm 256 bits aleatórios. Persistem apenas SHA-256
dos tokens; dada a entropia, a pré-imagem não é praticável. Access expira em 15
minutos. Refresh gira a cada uso; reuso revoga a sessão inteira. A sessão expira
após 30 dias absolutos ou sete dias sem refresh. Logout revoga a sessão; início de
exclusão revoga todas as sessões da conta na mesma transação. Estado `DELETING`
bloqueia identidade, refresh e novo login. Retenção e limpeza física dos registros
expirados são trabalho operacional antes de produção.

As tabelas de autenticação têm RLS forçada e acesso direto exclusivo do dono sem
login; papéis de runtime recebem apenas funções restritas. A identidade de tenant
vem de sessão válida, nunca de campo da requisição. A função de resolução verifica
novamente estado da conta e expiração no banco. Todas as respostas de auth usam
`Cache-Control: no-store`; o serviço não registra tokens brutos.

G-OIDC para configuração real requer comprovar os IDs de audiência e presenter
aprovados. G-DEPLOY, Google real em APK e HTTPS público continuam nas passadas
dependentes. A execução isolada usa somente PostgreSQL descartável no worker.
