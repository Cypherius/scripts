from django.apps import apps
from django.db import transaction
from django.db.models import Model, fields
from django.contrib.contenttypes.fields import GenericForeignKey


@transaction.atomic
    def merge_model_objects(primary_object, alias_objects=[], migrate_data=False, keep_old=False):
    """
    Use this function to merge model objects (i.e. Users, Organizations, Polls,
    etc.) and migrate all of the related fields from the alias objects to the
    primary object.

    Usage:
    from django.contrib.auth.models import User
    primary_user = User.objects.get(email='good_email@example.com')
    duplicate_user = User.objects.get(email='good_email+duplicate@example.com')
    merge_model_objects(primary_user, duplicate_user)
    """
    if not isinstance(alias_objects, list):
        alias_objects = [alias_objects]

    # check that all aliases are the same class as primary one and that
    # they are subclass of model
    primary_class = primary_object.__class__

    if not issubclass(primary_class, Model):
        raise TypeError('Only django.db.models.Model subclasses can be merged')

    for alias_object in alias_objects:
        if not isinstance(alias_object, primary_class):
            raise TypeError('Only models of same class can be merged')

    # Get a list of all GenericForeignKeys in all models
    # TODO: this is a bit of a hack, since the generics framework should provide a similar
    # method to the ForeignKey field for accessing the generic related fields.
    generic_fields = []
    for model in apps.get_models():
        for field_name, field in filter(lambda x: isinstance(x[1], GenericForeignKey), model.__dict__.iteritems()):
            generic_fields.append(field)

    blank_local_fields = set([field.attname for field in primary_object._meta.local_fields if getattr(primary_object, field.attname) in [None, '']])

    # Loop through all alias objects and migrate their data to the primary object.
    for alias_object in alias_objects:
        # Migrate all foreign key references from alias object to primary object.
        if migrate_data:
            for related_object in alias_object._meta.local_fields:
                if isinstance(related_object, fields.AutoField):
                    continue
                # The variable name on the alias_object model.
                alias_varname = related_object.get_accessor_name()
                # The variable name on the related model.
                obj_varname = related_object.field.name
                related_objects = getattr(alias_object, alias_varname).all() if hasattr(alias_object, alias_varname) else []
                for obj in related_objects:
                    setattr(obj, obj_varname, primary_object)
                    obj.save()

        # Migrate all many to many references from alias object to primary object.
        for related_many_object in get_all_related_many_to_many_objects(alias_object):
            alias_varname = related_many_object.get_accessor_name()
            obj_varname = related_many_object.field.name

            if alias_varname is not None:
                # standard case
                related_many_objects = getattr(alias_object, alias_varname).all()
            else:
                # special case, symmetrical relation, no reverse accessor
                related_many_objects = getattr(alias_object, obj_varname).all()
            for obj in related_many_objects.all():
                getattr(obj, obj_varname).remove(alias_object)
                getattr(obj, obj_varname).add(primary_object)

        # Migrate all one to one references from alias object to primary object
        for related_one_alias_object in get_all_related_one_to_one_objects(alias_object):
            alias_varname = related_one_alias_object.get_accessor_name()
            obj_varname = related_one_alias_object.field.name
            related_alias_object = getattr(alias_object, alias_varname) if hasattr(alias_object, alias_varname) \
                                        and not hasattr(primary_object, alias_varname) else None
            if related_alias_object:
                setattr(related_alias_object, obj_varname, primary_object)
                related_alias_object.save()

        # Migrate all foreign key references from alias object to primary object
        for related_foreignkey_object in get_all_related_one_to_many_objects(alias_object):
            alias_varname = related_foreignkey_object.get_accessor_name()
            obj_varname = related_foreignkey_object.field.name
            related_foreignkey_object = getattr(alias_object, alias_varname).all() if hasattr(alias_object, alias_varname) else []
            for obj in related_foreignkey_object:
                setattr(obj, obj_varname, primary_object)
                obj.save()

        # Try to fill all missing values in primary object by values of duplicates
        filled_up = set()
        for field_name in blank_local_fields:
            val = getattr(alias_object, field_name)
            if val not in [None, '']:
                setattr(primary_object, field_name, val)
                filled_up.add(field_name)
        blank_local_fields -= filled_up

        if not keep_old:
            alias_object.delete()
    primary_object.save()
    return primary_object