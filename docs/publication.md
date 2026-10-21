# Política do candidato público

Publicar somente arquivos explicitamente admitidos em public-allowlist.json e
revisados por conteúdo. A lista não autoriza publicação automática: o proprietário
revisa o candidato e o manifesto de hashes antes de autorizar a operação.

Histórico novo: criar commits iniciais em ambiente novo, sem copiar Git metadata,
refs, bundles, PRs, logs, artefatos, inventários ou relatórios privados. Nunca usar
fork, mirror, importador de histórico ou compartilhamento de objects/alternates.

Só incluir schemas, contratos, exemplos inventados e ferramentas/CI de conformidade.
Domínios de implantação são exemplos reservados; contas, credenciais, topologia,
custódia, incidentes e estados de runtime permanecem fora desta árvore.
As verificações automáticas detectam padrões conhecidos e arquivos inesperados;
a revisão humana final de contexto e informação operacional continua obrigatória.

O relatório de comparação e o procedimento de migração são artefatos privados de
revisão. Novos resultados de CI deverão ser gerados no novo repositório após
publicação autorizada; não importar resultados ou links de execução anteriores.
Publicação não implica implantação, merge, licença de distribuição ou início da 02.
