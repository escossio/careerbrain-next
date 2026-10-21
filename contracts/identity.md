# Identidade, sessão e isolamento V1

Android `com.escossio.careerbrain` usa Credential Manager e ID token destinado ao
Web Client ID público esperado pelo backend. O APK não tem client secret nem chave
de serviço. O backend verifica assinatura Google com biblioteca suportada, issuer,
audience, expiração, iat e nonce do desafio de login. Normalizar os dois emissores
Google suportados para `https://accounts.google.com`; nunca usar e-mail como chave.
JWKS/metadados vêm de hosts Google configurados; cabeçalho do token não escolhe URL.
`azp`, quando presente, deve pertencer aos clientes aprovados. IDs reais: G-OIDC.

`POST /v1/auth/challenges`: nonce imprevisível, expira em 5 minutos, uso único.
`POST /v1/auth/google`: token e challenge; replay de prova consumida é negado.
Nonce, iat/exp e clock skew tolerado pela política de auth não alteram publicação.
Token bruto nunca é persistido/logado. A 03 provará validação criptográfica real;
fixtures de claims da 01 não são teste de assinatura Google.

Identidade única `(canonical_issuer, sub)`. Criar usuário, tenant pessoal e vínculo
na mesma transação; concorrência, retry, reinstalação e segundo dispositivo recuperam
os mesmos IDs. `account_created_at` é UTC gerado pelo banco no primeiro commit,
imutável por constraints/permissões. Nenhum PATCH/import/upload/sessão muda a data.

Sessão própria revogável: access de 15 minutos, refresh opaco com rotação a cada
uso, expiração absoluta de 30 dias e inatividade máxima de 7 dias. Guardar somente
digest protegido do refresh. Reuso detectado revoga a família; logout revoga a
sessão; exclusão bloqueia todas imediatamente. Android usa armazenamento protegido
pelo sistema, sem backup/telemetria com tokens. Valores serão emitidos na 03.

Tenant vem do servidor. OIDC do usuário não autoriza ingestão ou administração.
Endpoints privados rejeitam escopo cruzado e estado DELETING antes de iniciar jobs.
Requisições não aceitam tenant/user escolhido pelo cliente. RLS é segunda barreira,
com prova SQL obrigatória na 02; um JSON com tenant_id não confere autoridade.

Exclusão completa encerra aquela conta. Novo cadastro após o expurgo é uma nova
conta com novo marco posterior; não recupera dados apagados nem reutiliza o marco
para liberar retroativos. Durante exclusão, login não recria a conta. O ledger
temporário impede ressurreição por jobs/restores e expira com os backups associados.
