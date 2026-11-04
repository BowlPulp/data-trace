{# Build every model straight into the profile schema (analytics), without prefixes. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
  {{ target.schema }}
{%- endmacro %}
