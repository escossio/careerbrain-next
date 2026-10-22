# Matching privado e corte temporal — execução 07

A migração 008 cria uma projeção de matching somente por tenant, evento,
`profile_version`, cache de classificação global e `policy_version`. A fila privada
guarda essas chaves e geração/epoch, nunca currículo, texto ou atributos privados.
O worker reivindica jobs com lease e fencing token e revalida conta ACTIVE, corte
temporal, evento, perfil, classificação e política dentro do commit.

`private.current_recommendations` é a fronteira de leitura. Ela só expõe projeções
compatíveis com as versões atuais e com `published_at >= account_created_at`; assim,
fechamento/retirada, exclusão, troca de perfil, política ou classificação não deixam
recomendação antiga visível. Uma reconciliação de evento inativo remove a projeção e
emite `REMOVED` no feed do próprio tenant.

A afinidade V1 só compara pares de atributo explícito com evidência exata. Não há
threshold, inferência de habilidade, veto por local/modalidade ou pontuação para dado
ausente. Sem comparação sustentada, a recomendação elegível traz
`REQUIREMENT_UNKNOWN` e afinidade/confiança `null`. O catálogo atual não representa
uma conclusão negativa comprovada sobre requisito obrigatório; portanto a 07 não
emite `REQUIREMENT_UNMET` por ausência de currículo. Essa extensão exigirá contrato
de evidência negativa revisado, não uma heurística.

Os testes descartáveis da passada cobrem corte antes/igual/depois com observação
tardia, replay idempotente, incerteza, remoção por lifecycle, troca de política,
fencing e leitura cross-tenant. A execução de PostgreSQL pertence somente ao worker
isolado; este documento não certifica ambiente produtivo ou dados reais.
