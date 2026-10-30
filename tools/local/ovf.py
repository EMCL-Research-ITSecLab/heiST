"""Standard-library OVF descriptor and digest helpers."""
import hashlib
import xml.etree.ElementTree as ET

OVF = 'http://schemas.dmtf.org/ovf/envelope/1'
RASD = 'http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData'
VSSD = 'http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData'


def ovf_document(name, disk_name, disk_size, capacity, memory_mb, cores, windows=False):
    ET.register_namespace('ovf', OVF)
    ET.register_namespace('rasd', RASD)
    ET.register_namespace('vssd', VSSD)
    def q(ns, tag):
        return '{' + ns + '}' + tag
    def child(parent, ns, tag, value=None, attrs=None):
        element = ET.SubElement(parent, q(ns, tag), attrs or {})
        if value is not None:
            element.text = str(value)
        return element
    envelope = ET.Element(q(OVF, 'Envelope'))
    refs = child(envelope, OVF, 'References')
    child(refs, OVF, 'File', attrs={q(OVF, 'id'): 'file1', q(OVF, 'href'): disk_name, q(OVF, 'size'): str(disk_size)})
    disks = child(envelope, OVF, 'DiskSection')
    child(disks, OVF, 'Info', 'Virtual disk')
    child(disks, OVF, 'Disk', attrs={q(OVF, 'diskId'): 'disk1', q(OVF, 'fileRef'): 'file1',
          q(OVF, 'capacity'): str(capacity), q(OVF, 'capacityAllocationUnits'): 'byte',
          q(OVF, 'format'): 'http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized'})
    system = child(envelope, OVF, 'VirtualSystem', attrs={q(OVF, 'id'): name})
    child(system, OVF, 'Info', 'heiST challenge VM; configure network and guest OS in heiST')
    child(system, OVF, 'Name', name)
    os_section = child(system, OVF, 'OperatingSystemSection', attrs={q(OVF, 'id'): '1'})
    child(os_section, OVF, 'Info', 'Guest OS')
    child(os_section, OVF, 'Description', 'Windows' if windows else 'Linux')
    hardware = child(system, OVF, 'VirtualHardwareSection')
    child(hardware, OVF, 'Info', 'CPU, memory, SATA boot disk; networking assigned at deployment')
    settings = child(hardware, OVF, 'System')
    child(settings, VSSD, 'ElementName', name)
    child(settings, VSSD, 'InstanceID', '0')
    child(settings, VSSD, 'VirtualSystemIdentifier', name)
    child(settings, VSSD, 'VirtualSystemType', 'vmx-07')
    def item(instance, resource, **values):
        element = child(hardware, OVF, 'Item')
        child(element, RASD, 'InstanceID', instance)
        child(element, RASD, 'ResourceType', resource)
        for key, value in values.items():
            child(element, RASD, key, value)
    item('1', '3', ElementName='CPU', VirtualQuantity=cores)
    item('2', '4', ElementName='Memory', AllocationUnits='byte * 2^20', VirtualQuantity=memory_mb)
    item('3', '20', ElementName='SATA Controller', ResourceSubType='vmware.sata.ahci', Address='0')
    item('4', '17', ElementName='Boot disk', HostResource='ovf:/disk/disk1', Parent='3', AddressOnParent='0')
    return ET.tostring(envelope, encoding='utf-8', xml_declaration=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(block)
    return h.hexdigest()
