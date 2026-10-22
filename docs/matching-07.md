# Matching privado e corte temporal — execução 07

A migração 008 cria uma projeção de matching somente por tenant, evento,
`profile_version`, cache de classificação global e `policy_version`. A fila privada
guarda essas chaves e geração/epoch, nunca currículo, texto ou atributos privados.
O worker reivindica jobs com lease e fencing token e revalida conta ACTIVE, corte
temporal, evento, perfil, classificação e política dentro do commit. A migração 009
é aditiva: retém o par de provas V2/V3 e não altera a interpretação de V1.

`private.current_recommendations` é a fronteira de leitura. Ela só expõe projeções
compatíveis com as versões atuais e com `published_at >= account_created_at`; assim,
fechamento/retirada, exclusão, troca de perfil, política ou classificação não deixam
recomendação antiga visível. Uma reconciliação de evento inativo remove a projeção e
emite `REMOVED` no feed do próprio tenant.

A afinidade V1 só compara pares de atributo explícito com evidência exata. Não há
threshold, inferência de habilidade, veto por local/modalidade ou pontuação para dado
ausente. Sem comparação sustentada, a recomendação elegível traz
`REQUIREMENT_UNKNOWN` e afinidade/confiança `null`. O catálogo V1 não representa
uma conclusão negativa comprovada; por isso não emite `REQUIREMENT_UNMET` por
ausência de currículo. A extensão V2/V3 exige `requirement_id`, nome e valor
idênticos num requisito obrigatório e num atestado explícito `NOT_MET`. Ambos retêm
`source_version`, campo, trecho e offsets validados antes da persistência. A
projeção guarda o par e esconde a recomendação; atributos V1/V2, texto heurístico
de currículo, ausência, local, modalidade e taxonomia nunca geram esse veto.

Os testes descartáveis da passada cobrem corte antes/igual/depois com observação
tardia, replay idempotente, incerteza, remoção por lifecycle, troca de política,
fencing e leitura cross-tenant, além do par positivo, negativa explícita e negativa
ausente/forjada. A execução de PostgreSQL pertence somente ao worker isolado; este
documento não certifica ambiente produtivo ou dados reais.
