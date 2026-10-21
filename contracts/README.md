# Contratos V1

Status: especificados e testáveis na passada 01; nenhuma implementação de API/DB.
Schemas JSON Schema 2020-12 em `v1/`; OpenAPI 3.1 em `openapi.json`. Referências
`careerbrain.invalid` são identificadores offline, nunca destinos de rede.

| Contrato | Semântica normativa |
| --- | --- |
| Ingestão/lote, receipt e erro | [ingestion.md](ingestion.md) |
| Proveniência, vaga/evento e lifecycle | [publication.md](publication.md) |
| Identidade, sessão e autorização | [identity.md](identity.md) |
| Currículo, perfil e exclusão | [privacy.md](privacy.md) |
| Classificação e matching | [semantics.md](semantics.md) |
| Cursor, candidatura e TTS | [client.md](client.md) |

JSON UTF-8 estrito, sem chaves duplicadas, NaN/Infinity ou propriedades extras.
Campos string não aceitam vazio/espaços como identidade/conteúdo. Instantes têm
segundos e fuso explícito (até microssegundos), são normalizados para UTC; datas
sem horário, leap seconds e offset além de ±14h são rejeitados. `format` é
validado explicitamente pelo harness; schema sozinho não verifica prova externa,
unicidade, transação ou autorização. Sem resolução remota de `$ref`.

Contrato aditivo só pode introduzir novos campos em versão explicitamente aceita;
`additionalProperties=false` impede evolução silenciosa. Incompatibilidade gera
novo identificador/rota; versão anterior só é removida com consumidores inventariados.
Exemplos são inventados, com domínio reservado `example.org` e datas controladas.
