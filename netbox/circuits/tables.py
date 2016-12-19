import django_tables2 as tables
from django_tables2.utils import Accessor

from utilities.tables import BaseTable, ToggleColumn

from .models import Circuit, CircuitType, Provider


CIRCUITTYPE_ACTIONS = """
{% if perms.circuit.change_circuittype %}
    <a href="{% url 'circuits:circuittype_edit' slug=record.slug %}" class="btn btn-xs btn-warning"><i class="glyphicon glyphicon-pencil" aria-hidden="true"></i></a>
{% endif %}
"""


#
# Providers
#

class ProviderTable(BaseTable):
    pk = ToggleColumn()
    name = tables.LinkColumn('circuits:provider', args=[Accessor('slug')], verbose_name='Name')
    asn = tables.Column(verbose_name='ASN')
    account = tables.Column(verbose_name='Account')
    circuit_count = tables.Column(accessor=Accessor('count_circuits'), verbose_name='Circuits')

    class Meta(BaseTable.Meta):
        model = Provider
        fields = ('pk', 'name', 'asn', 'account', 'circuit_count')


#
# Circuit types
#

class CircuitTypeTable(BaseTable):
    pk = ToggleColumn()
    name = tables.LinkColumn(verbose_name='Name')
    circuit_count = tables.Column(verbose_name='Circuits')
    slug = tables.Column(verbose_name='Slug')
    actions = tables.TemplateColumn(template_code=CIRCUITTYPE_ACTIONS, attrs={'td': {'class': 'text-right'}},
                                    verbose_name='')

    class Meta(BaseTable.Meta):
        model = CircuitType
        fields = ('pk', 'name', 'circuit_count', 'slug', 'actions')


#
# Circuits
#

class CircuitTable(BaseTable):
    pk = ToggleColumn()
    cid = tables.LinkColumn('circuits:circuit', args=[Accessor('pk')], verbose_name='ID')
    type = tables.Column(verbose_name='Type')
    provider = tables.LinkColumn('circuits:provider', args=[Accessor('provider.slug')], verbose_name='Provider')
    tenant = tables.LinkColumn('tenancy:tenant', args=[Accessor('tenant.slug')], verbose_name='Tenant')
    a_side = tables.LinkColumn('dcim:site', accessor=Accessor('termination_a.site'), orderable=False,
                               args=[Accessor('termination_a.site.slug')])
    z_side = tables.LinkColumn('dcim:site', accessor=Accessor('termination_z.site'), orderable=False,
                               args=[Accessor('termination_z.site.slug')])
    commit_rate = tables.Column(accessor=Accessor('commit_rate_human'), order_by=Accessor('commit_rate'),
                                verbose_name='Commit Rate')

    class Meta(BaseTable.Meta):
        model = Circuit
        fields = ('pk', 'cid', 'type', 'provider', 'tenant', 'a_side', 'z_side', 'commit_rate')
