# Evidência técnica da passada 03

Fonte de runtime testada: `a098269b93b7796d612a5afbe5e676dffefc24ea`.
Em job isolado, PostgreSQL descartável sem TCP/rede e papéis SQL de runtime reais:

- 18 testes de banco aprovados; restauração e reaplicação do ledger aprovadas.
- 12 testes de autenticação aprovados em 0,237 s: JWT RSA sintético válido e
  inválido, `aud`/`iss`/`azp`/nonce/tempo, challenge único e expirado,
  concorrência de login e refresh, estabilidade de conta, isolamento, logout,
  expiração e exclusão.
- Container temporário removido; inventário preexistente preservado. Logs do
  worker, dump sintético e detalhes operacionais ficam em evidência privada.

A revisão de publicação e os 49 testes offline passaram. O PR exige os checks
`contracts` e `repository-policy` no SHA final. O teste usa chave RSA inventada;
não houve sessão Google real nem uso de client IDs reais. Os IDs públicos OAuth
aprovados continuam necessários para certificar a configuração real da 03.
Por isso a 03 permanece BLOQUEADA para merge, apesar do aceite técnico offline.
Não houve deploy, banco de produção ou chamada faturável.
