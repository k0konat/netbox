from copy import deepcopy
import re
from natsort import natsorted
from operator import attrgetter

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import urlencode
from django.views.generic import View

from ipam.models import Prefix, IPAddress, Service, VLAN
from circuits.models import Circuit
from extras.models import Graph, TopologyMap, GRAPH_TYPE_INTERFACE, GRAPH_TYPE_SITE
from utilities.forms import ConfirmationForm
from utilities.views import (
    BulkDeleteView, BulkEditView, BulkImportView, ObjectDeleteView, ObjectEditView, ObjectListView,
)

from . import filters, forms, tables
from .models import (
    CONNECTION_STATUS_CONNECTED, ConsolePort, ConsolePortTemplate, ConsoleServerPort, ConsoleServerPortTemplate, Device,
    DeviceBay, DeviceBayTemplate, DeviceRole, DeviceType, Interface, InterfaceConnection, InterfaceTemplate,
    Manufacturer, Module, Platform, PowerOutlet, PowerOutletTemplate, PowerPort, PowerPortTemplate, Rack, RackGroup,
    RackRole, Site,
)


EXPANSION_PATTERN = '\[(\d+-\d+)\]'


def xstr(s):
    """
    Replace None with an empty string (for CSV export)
    """
    return '' if s is None else str(s)


def expand_pattern(string):
    """
    Expand a numeric pattern into a list of strings. Examples:
      'ge-0/0/[0-3]' => ['ge-0/0/0', 'ge-0/0/1', 'ge-0/0/2', 'ge-0/0/3']
      'xe-0/[0-3]/[0-7]' => ['xe-0/0/0', 'xe-0/0/1', 'xe-0/0/2', ... 'xe-0/3/5', 'xe-0/3/6', 'xe-0/3/7']
    """
    lead, pattern, remnant = re.split(EXPANSION_PATTERN, string, maxsplit=1)
    x, y = pattern.split('-')
    for i in range(int(x), int(y) + 1):
        if remnant:
            for string in expand_pattern(remnant):
                yield "{0}{1}{2}".format(lead, i, string)
        else:
            yield "{0}{1}".format(lead, i)


#
# Sites
#

class SiteListView(ObjectListView):
    queryset = Site.objects.select_related('tenant')
    filter = filters.SiteFilter
    filter_form = forms.SiteFilterForm
    table = tables.SiteTable
    edit_permissions = ['dcim.change_rack', 'dcim.delete_rack']
    template_name = 'dcim/site_list.html'


def site(request, slug):

    site = get_object_or_404(Site, slug=slug)
    stats = {
        'rack_count': Rack.objects.filter(site=site).count(),
        'device_count': Device.objects.filter(rack__site=site).count(),
        'prefix_count': Prefix.objects.filter(site=site).count(),
        'vlan_count': VLAN.objects.filter(site=site).count(),
        'circuit_count': Circuit.objects.filter(terminations__site=site).count(),
    }
    rack_groups = RackGroup.objects.filter(site=site).annotate(rack_count=Count('racks'))
    topology_maps = TopologyMap.objects.filter(site=site)
    show_graphs = Graph.objects.filter(type=GRAPH_TYPE_SITE).exists()

    return render(request, 'dcim/site.html', {
        'site': site,
        'stats': stats,
        'rack_groups': rack_groups,
        'topology_maps': topology_maps,
        'show_graphs': show_graphs,
    })


class SiteEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_site'
    model = Site
    form_class = forms.SiteForm
    template_name = 'dcim/site_edit.html'
    obj_list_url = 'dcim:site_list'


class SiteDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = 'dcim.delete_site'
    model = Site
    redirect_url = 'dcim:site_list'


class SiteBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.add_site'
    form = forms.SiteImportForm
    table = tables.SiteTable
    template_name = 'dcim/site_import.html'
    obj_list_url = 'dcim:site_list'


class SiteBulkEditView(PermissionRequiredMixin, BulkEditView):
    permission_required = 'dcim.change_site'
    cls = Site
    form = forms.SiteBulkEditForm
    template_name = 'dcim/site_bulk_edit.html'
    default_redirect_url = 'dcim:site_list'


#
# Rack groups
#

class RackGroupListView(ObjectListView):
    queryset = RackGroup.objects.select_related('site').annotate(rack_count=Count('racks'))
    filter = filters.RackGroupFilter
    filter_form = forms.RackGroupFilterForm
    table = tables.RackGroupTable
    edit_permissions = ['dcim.change_rackgroup', 'dcim.delete_rackgroup']
    template_name = 'dcim/rackgroup_list.html'


class RackGroupEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_rackgroup'
    model = RackGroup
    form_class = forms.RackGroupForm
    obj_list_url = 'dcim:rackgroup_list'
    use_obj_view = False


class RackGroupBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_rackgroup'
    cls = RackGroup
    default_redirect_url = 'dcim:rackgroup_list'


#
# Rack roles
#

class RackRoleListView(ObjectListView):
    queryset = RackRole.objects.annotate(rack_count=Count('racks'))
    table = tables.RackRoleTable
    edit_permissions = ['dcim.change_rackrole', 'dcim.delete_rackrole']
    template_name = 'dcim/rackrole_list.html'


class RackRoleEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_rackrole'
    model = RackRole
    form_class = forms.RackRoleForm
    obj_list_url = 'dcim:rackrole_list'
    use_obj_view = False


class RackRoleBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_rackrole'
    cls = RackRole
    default_redirect_url = 'dcim:rackrole_list'


#
# Racks
#

class RackListView(ObjectListView):
    queryset = Rack.objects.select_related('site', 'group', 'tenant', 'role').prefetch_related('devices__device_type')\
        .annotate(device_count=Count('devices', distinct=True))
    filter = filters.RackFilter
    filter_form = forms.RackFilterForm
    table = tables.RackTable
    edit_permissions = ['dcim.change_rack', 'dcim.delete_rack']
    template_name = 'dcim/rack_list.html'


def rack(request, pk):

    rack = get_object_or_404(Rack, pk=pk)

    nonracked_devices = Device.objects.filter(rack=rack, position__isnull=True, parent_bay__isnull=True)\
        .select_related('device_type__manufacturer')
    next_rack = Rack.objects.filter(site=rack.site, name__gt=rack.name).order_by('name').first()
    prev_rack = Rack.objects.filter(site=rack.site, name__lt=rack.name).order_by('-name').first()

    return render(request, 'dcim/rack.html', {
        'rack': rack,
        'nonracked_devices': nonracked_devices,
        'next_rack': next_rack,
        'prev_rack': prev_rack,
        'front_elevation': rack.get_front_elevation(),
        'rear_elevation': rack.get_rear_elevation(),
    })


class RackEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_rack'
    model = Rack
    form_class = forms.RackForm
    template_name = 'dcim/rack_edit.html'
    obj_list_url = 'dcim:rack_list'


class RackDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = 'dcim.delete_rack'
    model = Rack
    redirect_url = 'dcim:rack_list'


class RackBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.add_rack'
    form = forms.RackImportForm
    table = tables.RackImportTable
    template_name = 'dcim/rack_import.html'
    obj_list_url = 'dcim:rack_list'


class RackBulkEditView(PermissionRequiredMixin, BulkEditView):
    permission_required = 'dcim.change_rack'
    cls = Rack
    form = forms.RackBulkEditForm
    template_name = 'dcim/rack_bulk_edit.html'
    default_redirect_url = 'dcim:rack_list'


class RackBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_rack'
    cls = Rack
    default_redirect_url = 'dcim:rack_list'


#
# Manufacturers
#

class ManufacturerListView(ObjectListView):
    queryset = Manufacturer.objects.annotate(devicetype_count=Count('device_types'))
    table = tables.ManufacturerTable
    edit_permissions = ['dcim.change_manufacturer', 'dcim.delete_manufacturer']
    template_name = 'dcim/manufacturer_list.html'


class ManufacturerEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_manufacturer'
    model = Manufacturer
    form_class = forms.ManufacturerForm
    obj_list_url = 'dcim:manufacturer_list'
    use_obj_view = False


class ManufacturerBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_manufacturer'
    cls = Manufacturer
    default_redirect_url = 'dcim:manufacturer_list'


#
# Device types
#

class DeviceTypeListView(ObjectListView):
    queryset = DeviceType.objects.select_related('manufacturer').annotate(instance_count=Count('instances'))
    filter = filters.DeviceTypeFilter
    filter_form = forms.DeviceTypeFilterForm
    table = tables.DeviceTypeTable
    edit_permissions = ['dcim.change_devicetype', 'dcim.delete_devicetype']
    template_name = 'dcim/devicetype_list.html'


def devicetype(request, pk):

    devicetype = get_object_or_404(DeviceType, pk=pk)

    # Component tables
    consoleport_table = tables.ConsolePortTemplateTable(
        natsorted(ConsolePortTemplate.objects.filter(device_type=devicetype), key=attrgetter('name'))
    )
    consoleserverport_table = tables.ConsoleServerPortTemplateTable(
        natsorted(ConsoleServerPortTemplate.objects.filter(device_type=devicetype), key=attrgetter('name'))
    )
    powerport_table = tables.PowerPortTemplateTable(
        natsorted(PowerPortTemplate.objects.filter(device_type=devicetype), key=attrgetter('name'))
    )
    poweroutlet_table = tables.PowerOutletTemplateTable(
        natsorted(PowerOutletTemplate.objects.filter(device_type=devicetype), key=attrgetter('name'))
    )
    mgmt_interface_table = tables.InterfaceTemplateTable(InterfaceTemplate.objects.filter(device_type=devicetype,
                                                                                          mgmt_only=True))
    interface_table = tables.InterfaceTemplateTable(InterfaceTemplate.objects.filter(device_type=devicetype,
                                                                                     mgmt_only=False))
    devicebay_table = tables.DeviceBayTemplateTable(
        natsorted(DeviceBayTemplate.objects.filter(device_type=devicetype), key=attrgetter('name'))
    )
    if request.user.has_perm('dcim.change_devicetype'):
        consoleport_table.base_columns['pk'].visible = True
        consoleserverport_table.base_columns['pk'].visible = True
        powerport_table.base_columns['pk'].visible = True
        poweroutlet_table.base_columns['pk'].visible = True
        mgmt_interface_table.base_columns['pk'].visible = True
        interface_table.base_columns['pk'].visible = True
        devicebay_table.base_columns['pk'].visible = True

    return render(request, 'dcim/devicetype.html', {
        'devicetype': devicetype,
        'consoleport_table': consoleport_table,
        'consoleserverport_table': consoleserverport_table,
        'powerport_table': powerport_table,
        'poweroutlet_table': poweroutlet_table,
        'mgmt_interface_table': mgmt_interface_table,
        'interface_table': interface_table,
        'devicebay_table': devicebay_table,
    })


class DeviceTypeEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_devicetype'
    model = DeviceType
    form_class = forms.DeviceTypeForm
    template_name = 'dcim/devicetype_edit.html'
    obj_list_url = 'dcim:devicetype_list'


class DeviceTypeDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = 'dcim.delete_devicetype'
    model = DeviceType
    redirect_url = 'dcim:devicetype_list'


class DeviceTypeBulkEditView(PermissionRequiredMixin, BulkEditView):
    permission_required = 'dcim.change_devicetype'
    cls = DeviceType
    form = forms.DeviceTypeBulkEditForm
    template_name = 'dcim/devicetype_bulk_edit.html'
    default_redirect_url = 'dcim:devicetype_list'


class DeviceTypeBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_devicetype'
    cls = DeviceType
    default_redirect_url = 'dcim:devicetype_list'


#
# Device type components
#

class ComponentTemplateCreateView(View):
    model = None
    form = None

    def get(self, request, pk):

        devicetype = get_object_or_404(DeviceType, pk=pk)

        return render(request, 'dcim/component_template_add.html', {
            'devicetype': devicetype,
            'component_type': self.model._meta.verbose_name,
            'form': self.form(initial=request.GET),
            'cancel_url': reverse('dcim:devicetype', kwargs={'pk': devicetype.pk}),
        })

    def post(self, request, pk):

        devicetype = get_object_or_404(DeviceType, pk=pk)

        form = self.form(request.POST)
        if form.is_valid():

            component_templates = []
            for name in form.cleaned_data['name_pattern']:
                component_template = self.form(request.POST).save(commit=False)
                component_template.device_type = devicetype
                component_template.name = name
                try:
                    component_template.full_clean()
                    component_templates.append(component_template)
                except ValidationError:
                    form.add_error('name_pattern', "Duplicate name found: {}".format(name))

            if not form.errors:
                self.model.objects.bulk_create(component_templates)
                messages.success(request, u"Added {} component(s) to {}.".format(len(component_templates), devicetype))
                if '_addanother' in request.POST:
                    return redirect(request.path)
                else:
                    return redirect('dcim:devicetype', pk=devicetype.pk)

        return render(request, 'dcim/component_template_add.html', {
            'devicetype': devicetype,
            'component_type': self.model._meta.verbose_name,
            'form': form,
            'cancel_url': reverse('dcim:devicetype', kwargs={'pk': devicetype.pk}),
        })


class ConsolePortTemplateAddView(ComponentTemplateCreateView):
    model = ConsolePortTemplate
    form = forms.ConsolePortTemplateForm


class ConsolePortTemplateBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_consoleporttemplate'
    cls = ConsolePortTemplate
    parent_cls = DeviceType


class ConsoleServerPortTemplateAddView(ComponentTemplateCreateView):
    model = ConsoleServerPortTemplate
    form = forms.ConsoleServerPortTemplateForm


class ConsoleServerPortTemplateBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_consoleserverporttemplate'
    cls = ConsoleServerPortTemplate
    parent_cls = DeviceType


class PowerPortTemplateAddView(ComponentTemplateCreateView):
    model = PowerPortTemplate
    form = forms.PowerPortTemplateForm


class PowerPortTemplateBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_powerporttemplate'
    cls = PowerPortTemplate
    parent_cls = DeviceType


class PowerOutletTemplateAddView(ComponentTemplateCreateView):
    model = PowerOutletTemplate
    form = forms.PowerOutletTemplateForm


class PowerOutletTemplateBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_poweroutlettemplate'
    cls = PowerOutletTemplate
    parent_cls = DeviceType


class InterfaceTemplateAddView(ComponentTemplateCreateView):
    model = InterfaceTemplate
    form = forms.InterfaceTemplateForm


class InterfaceTemplateBulkEditView(PermissionRequiredMixin, BulkEditView):
    permission_required = 'dcim.change_interfacetemplate'
    cls = InterfaceTemplate
    parent_cls = DeviceType
    form = forms.InterfaceTemplateBulkEditForm
    template_name = 'dcim/interfacetemplate_bulk_edit.html'


class InterfaceTemplateBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_interfacetemplate'
    cls = InterfaceTemplate
    parent_cls = DeviceType


class DeviceBayTemplateAddView(ComponentTemplateCreateView):
    model = DeviceBayTemplate
    form = forms.DeviceBayTemplateForm


class DeviceBayTemplateBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_devicebaytemplate'
    cls = DeviceBayTemplate
    parent_cls = DeviceType


#
# Device roles
#

class DeviceRoleListView(ObjectListView):
    queryset = DeviceRole.objects.annotate(device_count=Count('devices'))
    table = tables.DeviceRoleTable
    edit_permissions = ['dcim.change_devicerole', 'dcim.delete_devicerole']
    template_name = 'dcim/devicerole_list.html'


class DeviceRoleEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_devicerole'
    model = DeviceRole
    form_class = forms.DeviceRoleForm
    obj_list_url = 'dcim:devicerole_list'
    use_obj_view = False


class DeviceRoleBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_devicerole'
    cls = DeviceRole
    default_redirect_url = 'dcim:devicerole_list'


#
# Platforms
#

class PlatformListView(ObjectListView):
    queryset = Platform.objects.annotate(device_count=Count('devices'))
    table = tables.PlatformTable
    edit_permissions = ['dcim.change_platform', 'dcim.delete_platform']
    template_name = 'dcim/platform_list.html'


class PlatformEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_platform'
    model = Platform
    form_class = forms.PlatformForm
    obj_list_url = 'dcim:platform_list'
    use_obj_view = False


class PlatformBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_platform'
    cls = Platform
    default_redirect_url = 'dcim:platform_list'


#
# Devices
#

class DeviceListView(ObjectListView):
    queryset = Device.objects.select_related('device_type__manufacturer', 'device_role', 'tenant', 'rack__site',
                                             'primary_ip4', 'primary_ip6')
    filter = filters.DeviceFilter
    filter_form = forms.DeviceFilterForm
    table = tables.DeviceTable
    edit_permissions = ['dcim.change_device', 'dcim.delete_device']
    template_name = 'dcim/device_list.html'


def device(request, pk):

    device = get_object_or_404(Device, pk=pk)
    console_ports = natsorted(
        ConsolePort.objects.filter(device=device).select_related('cs_port__device'), key=attrgetter('name')
    )
    cs_ports = natsorted(
        ConsoleServerPort.objects.filter(device=device).select_related('connected_console'), key=attrgetter('name')
    )
    power_ports = natsorted(
        PowerPort.objects.filter(device=device).select_related('power_outlet__device'), key=attrgetter('name')
    )
    power_outlets = natsorted(
        PowerOutlet.objects.filter(device=device).select_related('connected_port'), key=attrgetter('name')
    )
    interfaces = Interface.objects.filter(device=device, mgmt_only=False)\
        .select_related('connected_as_a', 'connected_as_b', 'circuit_termination__circuit')
    mgmt_interfaces = Interface.objects.filter(device=device, mgmt_only=True)\
        .select_related('connected_as_a', 'connected_as_b', 'circuit_termination__circuit')
    device_bays = natsorted(
        DeviceBay.objects.filter(device=device).select_related('installed_device__device_type__manufacturer'),
        key=attrgetter('name')
    )

    # Gather relevant device objects
    ip_addresses = IPAddress.objects.filter(interface__device=device).select_related('interface', 'vrf')\
        .order_by('address')
    services = Service.objects.filter(device=device)
    secrets = device.secrets.all()

    # Find any related devices for convenient linking in the UI
    related_devices = []
    if device.name:
        if re.match('.+[0-9]+$', device.name):
            # Strip 1 or more trailing digits (e.g. core-switch1)
            base_name = re.match('(.*?)[0-9]+$', device.name).group(1)
        elif re.match('.+\d[a-z]$', device.name.lower()):
            # Strip a trailing letter if preceded by a digit (e.g. dist-switch3a -> dist-switch3)
            base_name = re.match('(.*\d+)[a-z]$', device.name.lower()).group(1)
        else:
            base_name = None
        if base_name:
            related_devices = Device.objects.filter(name__istartswith=base_name).exclude(pk=device.pk)\
                .select_related('rack', 'device_type__manufacturer')[:10]

    # Show graph button on interfaces only if at least one graph has been created.
    show_graphs = Graph.objects.filter(type=GRAPH_TYPE_INTERFACE).exists()

    return render(request, 'dcim/device.html', {
        'device': device,
        'console_ports': console_ports,
        'cs_ports': cs_ports,
        'power_ports': power_ports,
        'power_outlets': power_outlets,
        'interfaces': interfaces,
        'mgmt_interfaces': mgmt_interfaces,
        'device_bays': device_bays,
        'ip_addresses': ip_addresses,
        'services': services,
        'secrets': secrets,
        'related_devices': related_devices,
        'show_graphs': show_graphs,
    })


class DeviceEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_device'
    model = Device
    form_class = forms.DeviceForm
    fields_initial = ['site', 'rack', 'position', 'face', 'device_bay']
    template_name = 'dcim/device_edit.html'
    obj_list_url = 'dcim:device_list'


class DeviceDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = 'dcim.delete_device'
    model = Device
    redirect_url = 'dcim:device_list'


class DeviceBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.add_device'
    form = forms.DeviceImportForm
    table = tables.DeviceImportTable
    template_name = 'dcim/device_import.html'
    obj_list_url = 'dcim:device_list'


class ChildDeviceBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.add_device'
    form = forms.ChildDeviceImportForm
    table = tables.DeviceImportTable
    template_name = 'dcim/device_import_child.html'
    obj_list_url = 'dcim:device_list'

    def save_obj(self, obj):
        # Inherent rack from parent device
        obj.rack = obj.parent_bay.device.rack
        obj.save()
        # Save the reverse relation
        device_bay = obj.parent_bay
        device_bay.installed_device = obj
        device_bay.save()


class DeviceBulkEditView(PermissionRequiredMixin, BulkEditView):
    permission_required = 'dcim.change_device'
    cls = Device
    form = forms.DeviceBulkEditForm
    template_name = 'dcim/device_bulk_edit.html'
    default_redirect_url = 'dcim:device_list'


class DeviceBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_device'
    cls = Device
    default_redirect_url = 'dcim:device_list'


def device_inventory(request, pk):

    device = get_object_or_404(Device, pk=pk)
    modules = Module.objects.filter(device=device, parent=None).select_related('manufacturer')\
        .prefetch_related('submodules')

    return render(request, 'dcim/device_inventory.html', {
        'device': device,
        'modules': modules,
    })


def device_lldp_neighbors(request, pk):

    device = get_object_or_404(Device, pk=pk)
    interfaces = Interface.objects.filter(device=device).select_related('connected_as_a', 'connected_as_b')

    return render(request, 'dcim/device_lldp_neighbors.html', {
        'device': device,
        'interfaces': interfaces,
    })


#
# Bulk device component creation
#

class DeviceBulkAddComponentView(View):
    """
    Add one or more components (e.g. interfaces) to a selected set of Devices.
    """
    form = forms.DeviceBulkAddComponentForm
    model = None
    model_form = None

    def get(self):
        return redirect('dcim:device_list')

    def post(self, request):

        # Are we editing *all* objects in the queryset or just a selected subset?
        if request.POST.get('_all'):
            pk_list = [int(pk) for pk in request.POST.get('pk_all').split(',') if pk]
        else:
            pk_list = [int(pk) for pk in request.POST.getlist('pk')]

        if '_create' in request.POST:
            form = self.form(request.POST)
            if form.is_valid():

                new_components = []
                data = deepcopy(form.cleaned_data)
                for device in data['pk']:

                    names = data['name_pattern']
                    for name in names:
                        component_data = {
                            'device': device.pk,
                            'name': name,
                        }
                        component_data.update(data)
                        component_form = self.model_form(component_data)
                        if component_form.is_valid():
                            new_components.append(component_form.save(commit=False))
                        else:
                            for field, errors in component_form.errors.as_data().items():
                                for e in errors:
                                    form.add_error(field, u'{} {}: {}'.format(device, name, ', '.join(e)))

                if not form.errors:
                    self.model.objects.bulk_create(new_components)
                    messages.success(request, u"Added {} {} to {} devices.".format(
                        len(new_components), self.model._meta.verbose_name_plural, len(form.cleaned_data['pk'])
                    ))
                    return redirect('dcim:device_list')

        else:
            form = self.form(initial={'pk': pk_list})

        selected_devices = Device.objects.filter(pk__in=pk_list)
        if not selected_devices:
            messages.warning(request, u"No devices were selected.")
            return redirect('dcim:device_list')

        return render(request, 'dcim/device_bulk_add_component.html', {
            'form': form,
            'component_name': self.model._meta.verbose_name_plural,
            'selected_devices': selected_devices,
            'cancel_url': reverse('dcim:device_list'),
        })


class DeviceBulkAddConsolePortView(DeviceBulkAddComponentView):
    model = ConsolePort
    model_form = forms.ConsolePortForm


class DeviceBulkAddConsoleServerPortView(DeviceBulkAddComponentView):
    model = ConsoleServerPort
    model_form = forms.ConsoleServerPortForm


class DeviceBulkAddPowerPortView(DeviceBulkAddComponentView):
    model = PowerPort
    model_form = forms.PowerPortForm


class DeviceBulkAddPowerOutletView(DeviceBulkAddComponentView):
    model = PowerOutlet
    model_form = forms.PowerOutletForm


class DeviceBulkAddInterfaceView(DeviceBulkAddComponentView):
    form = forms.DeviceBulkAddInterfaceForm
    model = Interface
    model_form = forms.InterfaceForm


class DeviceBulkAddDeviceBayView(DeviceBulkAddComponentView):
    model = DeviceBay
    model_form = forms.DeviceBayForm


#
# Console ports
#

@permission_required('dcim.add_consoleport')
def consoleport_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = forms.ConsolePortCreateForm(request.POST)
        if form.is_valid():

            console_ports = []
            for name in form.cleaned_data['name_pattern']:
                cp_form = forms.ConsolePortForm({
                    'device': device.pk,
                    'name': name,
                })
                if cp_form.is_valid():
                    console_ports.append(cp_form.save(commit=False))
                else:
                    form.add_error('name_pattern', "Duplicate console port name for this device: {}".format(name))

            if not form.errors:
                ConsolePort.objects.bulk_create(console_ports)
                messages.success(request, u"Added {} console port(s) to {}.".format(len(console_ports), device))
                if '_addanother' in request.POST:
                    return redirect('dcim:consoleport_add', pk=device.pk)
                else:
                    return redirect('dcim:device', pk=device.pk)

    else:
        form = forms.ConsolePortCreateForm()

    return render(request, 'dcim/device_component_add.html', {
        'device': device,
        'component_type': 'Console Port',
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.change_consoleport')
def consoleport_connect(request, pk):

    consoleport = get_object_or_404(ConsolePort, pk=pk)

    if request.method == 'POST':
        form = forms.ConsolePortConnectionForm(request.POST, instance=consoleport)
        if form.is_valid():
            consoleport = form.save()
            messages.success(request, u"Connected {} {} to {} {}.".format(
                consoleport.device,
                consoleport.name,
                consoleport.cs_port.device,
                consoleport.cs_port.name,
            ))
            return redirect('dcim:device', pk=consoleport.device.pk)

    else:
        form = forms.ConsolePortConnectionForm(instance=consoleport, initial={
            'rack': consoleport.device.rack,
            'connection_status': CONNECTION_STATUS_CONNECTED,
        })

    return render(request, 'dcim/consoleport_connect.html', {
        'consoleport': consoleport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleport.device.pk}),
    })


@permission_required('dcim.change_consoleport')
def consoleport_disconnect(request, pk):

    consoleport = get_object_or_404(ConsolePort, pk=pk)

    if not consoleport.cs_port:
        messages.warning(request, u"Cannot disconnect console port {}: It is not connected to anything."
                         .format(consoleport))
        return redirect('dcim:device', pk=consoleport.device.pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            consoleport.cs_port = None
            consoleport.connection_status = None
            consoleport.save()
            messages.success(request, u"Console port {} has been disconnected.".format(consoleport))
            return redirect('dcim:device', pk=consoleport.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/consoleport_disconnect.html', {
        'consoleport': consoleport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleport.device.pk}),
    })


class ConsolePortEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_consoleport'
    model = ConsolePort
    form_class = forms.ConsolePortForm


class ConsolePortDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = 'dcim.delete_consoleport'
    model = ConsolePort


class ConsolePortBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_consoleport'
    cls = ConsolePort
    parent_cls = Device


class ConsoleConnectionsBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.change_consoleport'
    form = forms.ConsoleConnectionImportForm
    table = tables.ConsoleConnectionTable
    template_name = 'dcim/console_connections_import.html'


#
# Console server ports
#

@permission_required('dcim.add_consoleserverport')
def consoleserverport_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = forms.ConsoleServerPortCreateForm(request.POST)
        if form.is_valid():

            cs_ports = []
            for name in form.cleaned_data['name_pattern']:
                csp_form = forms.ConsoleServerPortForm({
                    'device': device.pk,
                    'name': name,
                })
                if csp_form.is_valid():
                    cs_ports.append(csp_form.save(commit=False))
                else:
                    form.add_error('name_pattern', "Duplicate console server port name for this device: {}"
                                   .format(name))

            if not form.errors:
                ConsoleServerPort.objects.bulk_create(cs_ports)
                messages.success(request, u"Added {} console server port(s) to {}.".format(len(cs_ports), device))
                if '_addanother' in request.POST:
                    return redirect('dcim:consoleserverport_add', pk=device.pk)
                else:
                    return redirect('dcim:device', pk=device.pk)

    else:
        form = forms.ConsoleServerPortCreateForm()

    return render(request, 'dcim/device_component_add.html', {
        'device': device,
        'component_type': 'Console Server Port',
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.change_consoleserverport')
def consoleserverport_connect(request, pk):

    consoleserverport = get_object_or_404(ConsoleServerPort, pk=pk)

    if request.method == 'POST':
        form = forms.ConsoleServerPortConnectionForm(consoleserverport, request.POST)
        if form.is_valid():
            consoleport = form.cleaned_data['port']
            consoleport.cs_port = consoleserverport
            consoleport.connection_status = form.cleaned_data['connection_status']
            consoleport.save()
            messages.success(request, u"Connected {} {} to {} {}.".format(
                consoleport.device,
                consoleport.name,
                consoleserverport.device,
                consoleserverport.name,
            ))
            return redirect('dcim:device', pk=consoleserverport.device.pk)

    else:
        form = forms.ConsoleServerPortConnectionForm(consoleserverport, initial={'rack': consoleserverport.device.rack})

    return render(request, 'dcim/consoleserverport_connect.html', {
        'consoleserverport': consoleserverport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleserverport.device.pk}),
    })


@permission_required('dcim.change_consoleserverport')
def consoleserverport_disconnect(request, pk):

    consoleserverport = get_object_or_404(ConsoleServerPort, pk=pk)

    if not hasattr(consoleserverport, 'connected_console'):
        messages.warning(request, u"Cannot disconnect console server port {}: Nothing is connected to it."
                         .format(consoleserverport))
        return redirect('dcim:device', pk=consoleserverport.device.pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            consoleport = consoleserverport.connected_console
            consoleport.cs_port = None
            consoleport.connection_status = None
            consoleport.save()
            messages.success(request, u"Console server port {} has been disconnected.".format(consoleserverport))
            return redirect('dcim:device', pk=consoleserverport.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/consoleserverport_disconnect.html', {
        'consoleserverport': consoleserverport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': consoleserverport.device.pk}),
    })


class ConsoleServerPortEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_consoleserverport'
    model = ConsoleServerPort
    form_class = forms.ConsoleServerPortForm


class ConsoleServerPortDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = 'dcim.delete_consoleserverport'
    model = ConsoleServerPort


class ConsoleServerPortBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_consoleserverport'
    cls = ConsoleServerPort
    parent_cls = Device


#
# Power ports
#

@permission_required('dcim.add_powerport')
def powerport_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = forms.PowerPortCreateForm(request.POST)
        if form.is_valid():

            power_ports = []
            for name in form.cleaned_data['name_pattern']:
                pp_form = forms.PowerPortForm({
                    'device': device.pk,
                    'name': name,
                })
                if pp_form.is_valid():
                    power_ports.append(pp_form.save(commit=False))
                else:
                    form.add_error('name_pattern', "Duplicate power port name for this device: {}".format(name))

            if not form.errors:
                PowerPort.objects.bulk_create(power_ports)
                messages.success(request, u"Added {} power port(s) to {}.".format(len(power_ports), device))
                if '_addanother' in request.POST:
                    return redirect('dcim:powerport_add', pk=device.pk)
                else:
                    return redirect('dcim:device', pk=device.pk)

    else:
        form = forms.PowerPortCreateForm()

    return render(request, 'dcim/device_component_add.html', {
        'device': device,
        'component_type': 'Power Port',
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.change_powerport')
def powerport_connect(request, pk):

    powerport = get_object_or_404(PowerPort, pk=pk)

    if request.method == 'POST':
        form = forms.PowerPortConnectionForm(request.POST, instance=powerport)
        if form.is_valid():
            powerport = form.save()
            messages.success(request, u"Connected {} {} to {} {}.".format(
                powerport.device,
                powerport.name,
                powerport.power_outlet.device,
                powerport.power_outlet.name,
            ))
            return redirect('dcim:device', pk=powerport.device.pk)

    else:
        form = forms.PowerPortConnectionForm(instance=powerport, initial={
            'rack': powerport.device.rack,
            'connection_status': CONNECTION_STATUS_CONNECTED,
        })

    return render(request, 'dcim/powerport_connect.html', {
        'powerport': powerport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': powerport.device.pk}),
    })


@permission_required('dcim.change_powerport')
def powerport_disconnect(request, pk):

    powerport = get_object_or_404(PowerPort, pk=pk)

    if not powerport.power_outlet:
        messages.warning(request, u"Cannot disconnect power port {}: It is not connected to an outlet."
                         .format(powerport))
        return redirect('dcim:device', pk=powerport.device.pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            powerport.power_outlet = None
            powerport.connection_status = None
            powerport.save()
            messages.success(request, u"Power port {} has been disconnected.".format(powerport))
            return redirect('dcim:device', pk=powerport.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/powerport_disconnect.html', {
        'powerport': powerport,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': powerport.device.pk}),
    })


class PowerPortEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_powerport'
    model = PowerPort
    form_class = forms.PowerPortForm


class PowerPortDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = 'dcim.delete_powerport'
    model = PowerPort


class PowerPortBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_powerport'
    cls = PowerPort
    parent_cls = Device


class PowerConnectionsBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.change_powerport'
    form = forms.PowerConnectionImportForm
    table = tables.PowerConnectionTable
    template_name = 'dcim/power_connections_import.html'


#
# Power outlets
#

@permission_required('dcim.add_poweroutlet')
def poweroutlet_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = forms.PowerOutletCreateForm(request.POST)
        if form.is_valid():

            power_outlets = []
            for name in form.cleaned_data['name_pattern']:
                po_form = forms.PowerOutletForm({
                    'device': device.pk,
                    'name': name,
                })
                if po_form.is_valid():
                    power_outlets.append(po_form.save(commit=False))
                else:
                    form.add_error('name_pattern', "Duplicate power outlet name for this device: {}".format(name))

            if not form.errors:
                PowerOutlet.objects.bulk_create(power_outlets)
                messages.success(request, u"Added {} power outlet(s) to {}.".format(len(power_outlets), device))
                if '_addanother' in request.POST:
                    return redirect('dcim:poweroutlet_add', pk=device.pk)
                else:
                    return redirect('dcim:device', pk=device.pk)

    else:
        form = forms.PowerOutletCreateForm()

    return render(request, 'dcim/device_component_add.html', {
        'device': device,
        'component_type': 'Power Outlet',
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.change_poweroutlet')
def poweroutlet_connect(request, pk):

    poweroutlet = get_object_or_404(PowerOutlet, pk=pk)

    if request.method == 'POST':
        form = forms.PowerOutletConnectionForm(poweroutlet, request.POST)
        if form.is_valid():
            powerport = form.cleaned_data['port']
            powerport.power_outlet = poweroutlet
            powerport.connection_status = form.cleaned_data['connection_status']
            powerport.save()
            messages.success(request, u"Connected {} {} to {} {}.".format(
                powerport.device,
                powerport.name,
                poweroutlet.device,
                poweroutlet.name,
            ))
            return redirect('dcim:device', pk=poweroutlet.device.pk)

    else:
        form = forms.PowerOutletConnectionForm(poweroutlet, initial={'rack': poweroutlet.device.rack})

    return render(request, 'dcim/poweroutlet_connect.html', {
        'poweroutlet': poweroutlet,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': poweroutlet.device.pk}),
    })


@permission_required('dcim.change_poweroutlet')
def poweroutlet_disconnect(request, pk):

    poweroutlet = get_object_or_404(PowerOutlet, pk=pk)

    if not hasattr(poweroutlet, 'connected_port'):
        messages.warning(request, u"Cannot disconnect power outlet {}: Nothing is connected to it.".format(poweroutlet))
        return redirect('dcim:device', pk=poweroutlet.device.pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            powerport = poweroutlet.connected_port
            powerport.power_outlet = None
            powerport.connection_status = None
            powerport.save()
            messages.success(request, u"Power outlet {} has been disconnected.".format(poweroutlet))
            return redirect('dcim:device', pk=poweroutlet.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/poweroutlet_disconnect.html', {
        'poweroutlet': poweroutlet,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': poweroutlet.device.pk}),
    })


class PowerOutletEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_poweroutlet'
    model = PowerOutlet
    form_class = forms.PowerOutletForm


class PowerOutletDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = 'dcim.delete_poweroutlet'
    model = PowerOutlet


class PowerOutletBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_poweroutlet'
    cls = PowerOutlet
    parent_cls = Device


#
# Interfaces
#

@permission_required('dcim.add_interface')
def interface_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = forms.InterfaceCreateForm(request.POST)
        if form.is_valid():

            interfaces = []
            for name in form.cleaned_data['name_pattern']:
                iface_form = forms.InterfaceForm({
                    'device': device.pk,
                    'name': name,
                    'form_factor': form.cleaned_data['form_factor'],
                    'mac_address': form.cleaned_data['mac_address'],
                    'mgmt_only': form.cleaned_data['mgmt_only'],
                    'description': form.cleaned_data['description'],
                })
                if iface_form.is_valid():
                    interfaces.append(iface_form.save(commit=False))
                else:
                    form.add_error('name_pattern', "Duplicate interface name for this device: {}".format(name))

            if not form.errors:
                Interface.objects.bulk_create(interfaces)
                messages.success(request, u"Added {} interface(s) to {}.".format(len(interfaces), device))
                if '_addanother' in request.POST:
                    return redirect('dcim:interface_add', pk=device.pk)
                else:
                    return redirect('dcim:device', pk=device.pk)

    else:
        form = forms.InterfaceCreateForm(initial={'mgmt_only': request.GET.get('mgmt_only')})

    return render(request, 'dcim/device_component_add.html', {
        'device': device,
        'component_type': 'Interface',
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


class InterfaceEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_interface'
    model = Interface
    form_class = forms.InterfaceForm


class InterfaceDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = 'dcim.delete_interface'
    model = Interface


class InterfaceBulkEditView(PermissionRequiredMixin, BulkEditView):
    permission_required = 'dcim.change_interface'
    cls = Interface
    parent_cls = Device
    form = forms.InterfaceBulkEditForm
    template_name = 'dcim/interface_bulk_edit.html'


class InterfaceBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_interface'
    cls = Interface
    parent_cls = Device


#
# Device bays
#

@permission_required('dcim.add_devicebay')
def devicebay_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = forms.DeviceBayCreateForm(request.POST)
        if form.is_valid():

            device_bays = []
            for name in form.cleaned_data['name_pattern']:
                devicebay_form = forms.DeviceBayForm({
                    'device': device.pk,
                    'name': name,
                })
                if devicebay_form.is_valid():
                    device_bays.append(devicebay_form.save(commit=False))
                else:
                    for err in devicebay_form.errors.get('__all__', []):
                        form.add_error('name_pattern', err)

            if not form.errors:
                DeviceBay.objects.bulk_create(device_bays)
                messages.success(request, u"Added {} device bay(s) to {}.".format(len(device_bays), device))
                if '_addanother' in request.POST:
                    return redirect('dcim:devicebay_add', pk=device.pk)
                else:
                    return redirect('dcim:device', pk=device.pk)

    else:
        form = forms.DeviceBayCreateForm()

    return render(request, 'dcim/device_component_add.html', {
        'device': device,
        'component_type': 'Device Bay',
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


class DeviceBayEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_devicebay'
    model = DeviceBay
    form_class = forms.DeviceBayForm


class DeviceBayDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = 'dcim.delete_devicebay'
    model = DeviceBay


@permission_required('dcim.change_devicebay')
def devicebay_populate(request, pk):

    device_bay = get_object_or_404(DeviceBay, pk=pk)

    if request.method == 'POST':
        form = forms.PopulateDeviceBayForm(device_bay, request.POST)
        if form.is_valid():

            device_bay.installed_device = form.cleaned_data['installed_device']
            device_bay.save()

            if not form.errors:
                messages.success(request, u"Added {} to {}.".format(device_bay.installed_device, device_bay))
                return redirect('dcim:device', pk=device_bay.device.pk)

    else:
        form = forms.PopulateDeviceBayForm(device_bay)

    return render(request, 'dcim/devicebay_populate.html', {
        'device_bay': device_bay,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device_bay.device.pk}),
    })


@permission_required('dcim.change_devicebay')
def devicebay_depopulate(request, pk):

    device_bay = get_object_or_404(DeviceBay, pk=pk)

    if request.method == 'POST':
        form = ConfirmationForm(request.POST)
        if form.is_valid():
            removed_device = device_bay.installed_device
            device_bay.installed_device = None
            device_bay.save()
            messages.success(request, u"{} has been removed from {}.".format(removed_device, device_bay))
            return redirect('dcim:device', pk=device_bay.device.pk)

    else:
        form = ConfirmationForm()

    return render(request, 'dcim/devicebay_depopulate.html', {
        'device_bay': device_bay,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device_bay.device.pk}),
    })


class DeviceBayBulkDeleteView(PermissionRequiredMixin, BulkDeleteView):
    permission_required = 'dcim.delete_devicebay'
    cls = DeviceBay
    parent_cls = Device


#
# Interface connections
#

@permission_required('dcim.add_interfaceconnection')
def interfaceconnection_add(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = forms.InterfaceConnectionForm(device, request.POST)
        if form.is_valid():
            interfaceconnection = form.save()
            messages.success(request, u"Connected {} {} to {} {}.".format(
                interfaceconnection.interface_a.device,
                interfaceconnection.interface_a,
                interfaceconnection.interface_b.device,
                interfaceconnection.interface_b,
            ))
            if '_addanother' in request.POST:
                base_url = reverse('dcim:interfaceconnection_add', kwargs={'pk': device.pk})
                params = urlencode({
                    'rack_b': interfaceconnection.interface_b.device.rack.pk,
                    'device_b': interfaceconnection.interface_b.device.pk,
                })
                return HttpResponseRedirect('{}?{}'.format(base_url, params))
            else:
                return redirect('dcim:device', pk=device.pk)

    else:
        form = forms.InterfaceConnectionForm(device, initial={
            'interface_a': request.GET.get('interface_a', None),
            'site_b': request.GET.get('site_b', device.rack.site),
            'rack_b': request.GET.get('rack_b', None),
            'device_b': request.GET.get('device_b', None),
            'interface_b': request.GET.get('interface_b', None),
        })

    return render(request, 'dcim/interfaceconnection_edit.html', {
        'device': device,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


@permission_required('dcim.delete_interfaceconnection')
def interfaceconnection_delete(request, pk):

    interfaceconnection = get_object_or_404(InterfaceConnection, pk=pk)
    device_id = request.GET.get('device', None)

    if request.method == 'POST':
        form = forms.InterfaceConnectionDeletionForm(request.POST)
        if form.is_valid():
            interfaceconnection.delete()
            messages.success(request, u"Deleted the connection between {} {} and {} {}.".format(
                interfaceconnection.interface_a.device,
                interfaceconnection.interface_a,
                interfaceconnection.interface_b.device,
                interfaceconnection.interface_b,
            ))
            if form.cleaned_data['device']:
                return redirect('dcim:device', pk=form.cleaned_data['device'].pk)
            else:
                return redirect('dcim:device_list')

    else:
        form = forms.InterfaceConnectionDeletionForm(initial={
            'device': device_id,
        })

    # Determine where to direct user upon cancellation
    if device_id:
        cancel_url = reverse('dcim:device', kwargs={'pk': device_id})
    else:
        cancel_url = reverse('dcim:device_list')

    return render(request, 'dcim/interfaceconnection_delete.html', {
        'interfaceconnection': interfaceconnection,
        'device_id': device_id,
        'form': form,
        'cancel_url': cancel_url,
    })


class InterfaceConnectionsBulkImportView(PermissionRequiredMixin, BulkImportView):
    permission_required = 'dcim.change_interface'
    form = forms.InterfaceConnectionImportForm
    table = tables.InterfaceConnectionTable
    template_name = 'dcim/interface_connections_import.html'


#
# Connections
#

class ConsoleConnectionsListView(ObjectListView):
    queryset = ConsolePort.objects.select_related('device', 'cs_port__device').filter(cs_port__isnull=False)\
        .order_by('cs_port__device__name', 'cs_port__name')
    filter = filters.ConsoleConnectionFilter
    filter_form = forms.ConsoleConnectionFilterForm
    table = tables.ConsoleConnectionTable
    template_name = 'dcim/console_connections_list.html'


class PowerConnectionsListView(ObjectListView):
    queryset = PowerPort.objects.select_related('device', 'power_outlet__device').filter(power_outlet__isnull=False)\
        .order_by('power_outlet__device__name', 'power_outlet__name')
    filter = filters.PowerConnectionFilter
    filter_form = forms.PowerConnectionFilterForm
    table = tables.PowerConnectionTable
    template_name = 'dcim/power_connections_list.html'


class InterfaceConnectionsListView(ObjectListView):
    queryset = InterfaceConnection.objects.select_related('interface_a__device', 'interface_b__device')\
        .order_by('interface_a__device__name', 'interface_a__name')
    filter = filters.InterfaceConnectionFilter
    filter_form = forms.InterfaceConnectionFilterForm
    table = tables.InterfaceConnectionTable
    template_name = 'dcim/interface_connections_list.html'


#
# IP addresses
#

@permission_required(['dcim.change_device', 'ipam.add_ipaddress'])
def ipaddress_assign(request, pk):

    device = get_object_or_404(Device, pk=pk)

    if request.method == 'POST':
        form = forms.IPAddressForm(device, request.POST)
        if form.is_valid():

            ipaddress = form.save(commit=False)
            ipaddress.interface = form.cleaned_data['interface']
            ipaddress.save()
            form.save_custom_fields()
            messages.success(request, u"Added new IP address {} to interface {}.".format(ipaddress, ipaddress.interface))

            if form.cleaned_data['set_as_primary']:
                if ipaddress.family == 4:
                    device.primary_ip4 = ipaddress
                elif ipaddress.family == 6:
                    device.primary_ip6 = ipaddress
                device.save()

            if '_addanother' in request.POST:
                return redirect('dcim:ipaddress_assign', pk=device.pk)
            else:
                return redirect('dcim:device', pk=device.pk)

    else:
        form = forms.IPAddressForm(device)

    return render(request, 'dcim/ipaddress_assign.html', {
        'device': device,
        'form': form,
        'cancel_url': reverse('dcim:device', kwargs={'pk': device.pk}),
    })


#
# Modules
#

class ModuleEditView(PermissionRequiredMixin, ObjectEditView):
    permission_required = 'dcim.change_module'
    model = Module
    form_class = forms.ModuleForm

    def alter_obj(self, obj, args, kwargs):
        if 'device' in kwargs:
            device = get_object_or_404(Device, pk=kwargs['device'])
            obj.device = device
        return obj


class ModuleDeleteView(PermissionRequiredMixin, ObjectDeleteView):
    permission_required = 'dcim.delete_module'
    model = Module
