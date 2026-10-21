# Evidência técnica da passada 06

A fonte `9879dcef3f442b46bf0e4c6f72267bfdba8009d8` passou no CI03 descartável,
sem rede: 18 testes SQL, restauração/ledger, 12 de autenticação, 12 de ingestão,
11 de classificação e 11 de currículo. Os casos de currículo cobrem sucesso,
incerteza, limites defensivos, idempotência, geração/epoch, cancelamento,
interrupção, perda de temporário, expiração, limpeza, isolamento de tenant,
multipart autenticado e limites de memória/swap/core dump. O PostgreSQL foi
removido e os containers preexistentes foram preservados.

No PR #9, `contracts` e `repository-policy` aprovaram a fonte final
`67359a9c01a8aa170e49c6073dd48e25a6f12ece`; ela foi integrada por squash como
`e884cefb40dc4871f7361a6bc41c493d950f9362`. Logs, hashes e inventários
operacionais ficam em checkpoint privado.

O teste prova somente o runtime isolado. Currículos reais, tráfego de IA e a
proteção do ambiente produtivo permanecem fora desta execução.
