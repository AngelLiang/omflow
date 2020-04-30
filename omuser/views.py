'''
django view for omflow.omuser , process user login/logout/register
@author: Pen Lin
'''
from django.shortcuts import render
from django.contrib import auth
from django.utils.translation import gettext as _
from omflow.syscom.message import ResponseAjax, statusEnum
from omflow.syscom.common import checkEmailFormat, DatatableBuilder, try_except, DataChecker, check_ldap_app, DataFormat
from omflow.syscom.license import getUsers
from omuser.models import OmUser, OmGroup
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, Permission
import uuid, base64, json
from datetime import datetime, timedelta
from django.views.decorators.csrf import csrf_exempt
from omflow.global_obj import GlobalObject
from django.forms.models import model_to_dict
from django.http.response import JsonResponse
from ommessage.models import MessageHistory, HistoryMembers
from omflow.syscom.default_logger import info,debug,error
from ast import literal_eval
from django.conf import settings
from django.contrib.sessions.models import Session
from distutils.util import strtobool
from omflow.models import SystemSetting
if check_ldap_app():
    from omldap.ldap_config import check_LDAP_auth


# Create your views here.
def loginPage(request):
    '''
    show login page
    input:request
    return: login.html
    author:Pen Lin
    ''' 
    if request.user.is_authenticated:
        return render(request, "home.html")
    else:
        return render(request, "login.html")


@csrf_exempt
def loginAjax(request):
    '''
    login to omflow , using post
    input: request.headers['Authorization']
    return: json
    author: Kolin Hsu
    ''' 
    try:
        #get request headers
        basic_auth_str = request.headers['Authorization'][6:]
        username, password = base64.b64decode(basic_auth_str).decode('utf-8').split(':')
        #Server Side Rule Check
        if checkEmailFormat(username):
            usersearch = OmUser.objects.get(email=username)
        else:
            usersearch = OmUser.objects.get(username__icontains=username)
        username_db = usersearch.username
        ad_flag = usersearch.ad_flag
        if ad_flag:
            if check_LDAP_auth(username_db, password) and check_ldap_app():
                user = OmUser.objects.get(username=username_db)
            else:
                return ResponseAjax(statusEnum.no_permission ,  _('登入失敗')).returnJSON()
        else:
            user = auth.authenticate(username=username_db, password=password)
        if user is not None and user.is_active:
            #check this username has already logged in or not
            session_obj_list = Session.objects.all()
            for session_obj in session_obj_list:
                user_id = session_obj.get_decoded().get("_auth_user_id")
                web_login = session_obj.get_decoded().get("web_login")
                if user_id == str(user.id) and web_login:
                    session_obj.delete()
                    break
            auth.login(request, user)
            request.session['web_login'] = True
            request.session.set_expiry(130)
            info(request ,'%s Login success' % request.user.username)
            return ResponseAjax(statusEnum.success,  _('登入成功')).returnJSON()
        else:
            info(request ,'%s Login failure' % request.user.username)
            return ResponseAjax(statusEnum.no_permission ,  _('登入失敗')).returnJSON()
    except Exception as e:
        error(request,e)
        return ResponseAjax(statusEnum.no_permission ,  _('登入失敗，查無此使用者帳號。')).returnJSON()


@csrf_exempt
def checkMultipleLoginAjax(request):
    '''
    check this username has already logged in or not
    input: request.headers['Authorization']
    return: json
    author: Kolin Hsu
    ''' 
    try:
        #function variable
        already_login = False
        already_login_message = ''
        #get request headers
        basic_auth_str = request.headers['Authorization'][6:]
        username, password = base64.b64decode(basic_auth_str).decode('utf-8').split(':')
        #Server Side Rule Check
        if checkEmailFormat(username):
            usersearch = OmUser.objects.get(email=username)
        else:
            usersearch = OmUser.objects.get(username__icontains=username)
        username_db = usersearch.username
        ad_flag = usersearch.ad_flag
        if ad_flag:
            if check_LDAP_auth(username_db, password) and check_ldap_app():
                user = OmUser.objects.get(username=username_db)
            else:
                return ResponseAjax(statusEnum.no_permission ,  _('登入失敗')).returnJSON()
        else:
            user = auth.authenticate(username=username_db, password=password)
        if user is not None and user.is_active:
            #check this username has already logged in or not
            session_obj_list = Session.objects.all()
            for session_obj in session_obj_list:
                user_id = session_obj.get_decoded().get("_auth_user_id")
                web_login = session_obj.get_decoded().get("web_login")
                if user_id == str(user.id) and web_login:
                    expire_date = session_obj.expire_date
                    if expire_date > datetime.now():
                        already_login_message = _('帳號已登入，是否取代線上使用者？')
                        already_login = True
                        break
                    else:
                        session_obj.delete()
                        break
            if already_login:
                return ResponseAjax(statusEnum.success,  _('重複登入'), already_login).returnJSON()
            else:
                auth.login(request, user)
                request.session['web_login'] = True
                request.session.set_expiry(130)
                info(request ,'%s Login success' % request.user.username)
                return ResponseAjax(statusEnum.success,  already_login_message, already_login).returnJSON()
        else:
            info(request ,'%s Login failure' % request.user.username)
            return ResponseAjax(statusEnum.no_permission ,  _('登入失敗')).returnJSON()
    except Exception as e:
        error(request,e)
        return ResponseAjax(statusEnum.no_permission ,  _('登入失敗，查無此使用者帳號。')).returnJSON()


def logoutPage(request):
    '''
    logout user , then draw login page
    input:request
    return: login.html
    author:Pen Lin
    ''' 
    auth.logout(request)
    return render(request, "login.html")
    
    
def registerPage(request):
    '''
    show register new user page
    input:request
    return: register.html
    author:Pen Lin
    ''' 
    return render(request, "register.html")


@csrf_exempt
def registerAjax(request):
    '''
    register a new user , superuser permission for first register
    input:request
    return: json
    author:Pen Lin, Kolin Hsu
    ''' 
    license_user_num = getUsers('')
    now_users_num = OmUser.objects.filter(delete=False,is_active=False).exclude(username='system').count()
    if now_users_num < license_user_num:
        #function variable
        error_message = _('註冊失敗：')
        #Server Side Rule Check
        require_field = ['username', 'email_@', 'token', 'token2']
        postdata = request.POST
        checker = DataChecker(postdata, require_field)
        if checker.get('status') == 'success':
            #get data
            requestJson = {}
            if request.POST.get('username') is not None:
                postdata = request.POST
            else:
                postdata = json.loads(request.body.decode("utf-8"))
            
            requestJson['username'] = postdata.get('username', '')
            requestJson['email'] = postdata.get('email_@', '')
            requestJson['password'] = postdata.get('token', '')
            requestJson['password2'] = postdata.get('token2', '')
            #Server Side Rule Check
            if requestJson['password'] == requestJson['password2']:
                #get all user count  , if count is 0, then create super user.
                if OmUser.objects.count() == 1:
                    #create super user
                    try:
                        user = OmUser.objects.create_superuser(username=requestJson['username'], nick_name=requestJson['username'], email=requestJson['email'],password=requestJson['password'])
                    except:
                        user = None
                else:
                    try:
                        OmUser.objects.get(username__icontains=requestJson['username'])
                        user = None
                        error_message += _('使用者名稱已被註冊。')
                    except:
                        try:
                            user = OmUser.objects.create_user(username=requestJson['username'], nick_name=requestJson['username'], email=requestJson['email'],password=requestJson['password'])
                        except:
                            user = None
                            error_message += _('電子郵件已被註冊。')
                    
                if user is not None:
                    return ResponseAjax(statusEnum.success,  _('註冊成功')).returnJSON()
                else:
                    return ResponseAjax(statusEnum.no_permission, error_message).returnJSON()
            else:
                error_message += _('兩次輸入的密碼不相同。')
                return ResponseAjax(statusEnum.no_permission, error_message).returnJSON()
        else:
            return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()
    else:
        return ResponseAjax(statusEnum.not_found, _('使用者數量已達上限，請向原廠購買授權。')).returnJSON()


@login_required
def profilePage(request, url):
    '''
    show user profile page
    input:request
    return: profile page
    author: Kolin Hsu
    '''
    username = url.split('/')[0]
    if (request.user.has_perm('omuser.OmUser_View') or (username == request.user.username)) and (username != ''):
        return render(request, "profile.html", locals())
    elif request.user.has_perm('omuser.OmUser_Add') and (username == ''):
        return render(request, "profile.html", locals())
    else:
        return render(request, "403.html")


@login_required
@try_except
def loadUserAjax(request):
    '''
    show user profile
    input: request
    return: user jsonArray
    author: Kolin Hsu
    '''
    username = request.POST.get('username_click', '')
    result = {}
    if  request.user.username == username or request.user.has_perm('omuser.OmUser_View'):
        #Server Side Rule Check
        require_field = ['username_click']
        postdata = request.POST
        checker = DataChecker(postdata, require_field)
        if checker.get('status') == 'success':
            user_now = list(OmUser.objects.filter(username=username).values('username','password','company','nick_name','email','department','birthday','gender','phone1','phone2','frequency','ad_flag'))[0]
            if user_now['birthday']:
                user_now['birthday'] = str(user_now['birthday'].strftime(settings.DATE_FORMAT))
            user = OmUser.objects.get(username=username)
            user_group_list = list(user.groups.filter(omgroup__functional_flag=False,omgroup__ad_flag=False).values_list('name',flat=True))
            user_role_list = list(user.groups.filter(omgroup__functional_flag=True,omgroup__ad_flag=False).values_list('name',flat=True))
            user_adgroup_list = list(user.groups.filter(omgroup__functional_flag=False,omgroup__ad_flag=True).values_list('omgroup__display_name',flat=True))
            result['user'] = user_now
            result['user_group_list'] = user_group_list
            result['user_role_list'] = user_role_list
            result['user_adgroup_list'] = user_adgroup_list
            if request.user.has_perm('omuser.OmGroup_View'):
                group_list = list(OmGroup.objects.filter(ad_flag=False).values('id','name','parent_group','functional_flag','description').order_by('parent_group', '-id'))
                result['group_list'] = group_list
            info(request ,'%s load user success' % request.user.username)
            return ResponseAjax(statusEnum.success , _('讀取成功'), result).returnJSON()
        else:
            info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
            return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()
    else:
        info(request ,'%s has no permission.' % request.user.username)
        return ResponseAjax(statusEnum.no_permission ,  _('您沒有權限進行此操作。')).returnJSON()
    

@login_required
@try_except
def updateUserAjax(request):
    '''
    update user profile
    input:request
    return: json
    author: Kolin Hsu
    ''' 
    postdata = request.POST
    username = postdata.get('username', '')
    token = postdata.get('token','')
    if  username == request.user.username or request.user.has_perm('omuser.OmUser_Modify'):
        #Server Side Rule Check
        require_field = ['username','nick_name','email_@','refresh_rate_$']
        checker = DataChecker(postdata, require_field)
        if checker.get('status') == 'success':
            user = OmUser.objects.get(username=username)
            user.nick_name = postdata.get('nick_name', '')
            if postdata.get('birthday_%Y', ''):
                user.birthday = postdata.get('birthday_%Y', '')
            else:
                user.birthday = None
            user.gender = postdata.get('gender', '')
            user.email = postdata.get('email_@', '')
            user.phone1 = postdata.get('phone1', '')
            user.phone2 = postdata.get('phone2', '')
            user.department = postdata.get('department', '')
            user.company = postdata.get('company', '')
            user.frequency = postdata.get('refresh_rate_$', '')
            if request.user.username != username and token != user.password and user.ad_flag == False and token:
                user.set_password(postdata.get('token', ''))
            user.save()
        else:
            info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
            return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()
    else:
        user = None
        
    if user is not None:
        info(request ,'%s update user success' % request.user.username)
        return ResponseAjax(statusEnum.success,  _('更新成功')).returnJSON()
    else:
        info(request ,'%s update user success' % request.user.username)
        return ResponseAjax(statusEnum.no_permission ,  _('更新失敗')).returnJSON()
    

@login_required
@permission_required('omuser.OmUser_View','/page/403/')
def userManagementPage(request):
    '''
    show user Management page
    input:request
    return: userManage page
    author: Kolin Hsu
    '''
    return render(request, "user_manage.html")


@login_required
@permission_required('omuser.OmUser_View','/api/permission/denied/')
@try_except
def listUserAjax(request):
    '''
    show all user list
    input: request
    return: user object
    author: Kolin Hsu, Pei lin
    '''
    is_active = request.POST.getlist('is_active[]',['1','0'])
    ad_flag = request.POST.getlist('ad_flag[]',['1','0'])
    filed_list=['username__icontains','nick_name__icontains','email__icontains','company__icontains','department__icontains']
    display_field = ['username','email','nick_name','company','is_active','department','ad_flag','last_login','id','is_superuser']
    userquery = OmUser.objects.filter(is_active__in=is_active, ad_flag__in=ad_flag, delete=False).exclude(id=1).values(*display_field)
    result = DatatableBuilder(request, userquery, filed_list)
    info(request ,'%s list user success' % request.user.username)
    return JsonResponse(result)


@login_required
@permission_required('omuser.OmUser_Add','/api/permission/denied/')
@try_except
def addUserAjax(request):
    '''
    add user
    input: request
    return: json
    author: Kolin Hsu
    '''
    license_user_num = getUsers('')
    now_users_num = OmUser.objects.filter(delete=False,is_active=False).exclude(username='system').count()
    if now_users_num < license_user_num:
        postdata = request.POST
        #Server Side Rule Check
        require_field = ['username','nick_name','email_@','refresh_rate_$','token']
        checker = DataChecker(postdata, require_field)
        if checker.get('status') == 'success':
            username = postdata.get('username', '')
            email = postdata.get('email_@', '')
            password = postdata.get('token', '')
            nick_name = postdata.get('nick_name', '')
            birthday = None
            if postdata.get('birthday_%Y', ''):
                birthday = postdata.get('birthday_%Y')
            gender = postdata.get('gender', '')
            phone1 = postdata.get('phone1', '')
            phone2 = postdata.get('phone2', '')
            department = postdata.get('department', '')
            company = postdata.get('company', '')
            if not OmUser.objects.filter(username=username).exists():
                try:
                    OmUser.objects.create_user(username=username, email=email, password=password, nick_name=nick_name, birthday=birthday, gender=gender, phone1=phone1, phone2=phone2, department=department, company=company)
                except:
                    info(request ,'%s add user error' % request.user.username)
                    return ResponseAjax(statusEnum.no_permission,  _('新增使用者失敗')).returnJSON()
            else:
                info(request ,'%s add user error' % request.user.username)
                return ResponseAjax(statusEnum.no_permission ,  _('該使用者名稱已經被使用')).returnJSON()
            info(request ,'%s add user success' % request.user.username)
            return ResponseAjax(statusEnum.success,  _('新增使用者成功')).returnJSON()
        else:
            info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
            return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()
    else:
        info(request ,'%s the license error.' % request.user.username)
        return ResponseAjax(statusEnum.not_found, _('使用者數量已達上限，請向原廠購買授權。')).returnJSON()


@login_required
@permission_required('omuser.OmUser_Delete','/api/permission/denied/')
@try_except
def deleteUserAjax(request):
    '''
    delete user
    input: request
    return: json
    author: Kolin Hsu
    '''
    #Server Side Rule Check
    require_field = ['username[]']
    postdata = request.POST
    checker = DataChecker(postdata, require_field)
    if checker.get('status') == 'success':
        try:
            user_arr = request.POST.getlist('username[]', '')
            for username in user_arr:
                user = OmUser.objects.get(username=username)
                if user.is_superuser:
                    return ResponseAjax(statusEnum.no_permission,  _('無法刪除系統管理員')).returnJSON()
                #修改該使用者所有關聯的message history
                his_id_list = list(HistoryMembers.objects.filter(user_id=user.id).values_list('id',flat=True))
                for his_id in his_id_list:
                    delete_users_list = []
                    messagehistory = MessageHistory.objects.get(id=his_id)
                    if messagehistory.delete_users_username:
                        delete_users_list = literal_eval(messagehistory.delete_users_username)
                    delete_users_list.append(user.username)
                    messagehistory.delete_users_username = delete_users_list
                    messagehistory.save()
                #刪除使用者
                user.delete = True
                user.save()
            info(request ,'%s delete user success' % request.user.username)
            return ResponseAjax(statusEnum.success, _('刪除使用者成功'), user_arr).returnJSON()
        except Exception as e:
            error(request,e)
            return ResponseAjax(statusEnum.error, e.__str__()).returnJSON()
    else:
        info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
        return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()


@login_required
@permission_required('omuser.OmUser_Modify','/api/permission/denied/')
@try_except
def activeUserAjax(request):
    '''
    delete user
    input: request
    return: json
    author: Kolin Hsu
    '''
    postdata = request.POST
    #Server Side Rule Check
    require_field = ['username[]', 'status']
    checker = DataChecker(postdata, require_field)
    status = postdata.get('status', '')
    user_arr = postdata.getlist('username[]', '')
    superuser_name_list = list(OmUser.objects.filter(is_superuser=True).values_list('username',flat=True))
    if checker.get('status') == 'success':
        for superuser_name in superuser_name_list:
            if superuser_name in user_arr:
                info(request ,'%s cannot inactive superuser.' % request.user.username)
                return ResponseAjax(statusEnum.error,  _('無法停用系統管理員')).returnJSON()
        if status == 'active':
            license_user_num = getUsers('')
            now_users_num = OmUser.objects.filter(delete=False,is_active=False).exclude(username='system').count()
            if now_users_num < license_user_num:
                OmUser.objects.filter(username__in=user_arr).update(is_active=True)
                info(request ,'%s active user success' % request.user.username)
                return ResponseAjax(statusEnum.success,  _('啟用使用者成功'), user_arr).returnJSON()
            else:
                info(request ,'%s the license error.' % request.user.username)
                return ResponseAjax(statusEnum.not_found, _('使用者數量已達上限，請向原廠購買授權。')).returnJSON()
        elif status == 'inactive':
            OmUser.objects.filter(username__in=user_arr).update(is_active=False)
            info(request ,'%s inactive user success' % request.user.username)
            return ResponseAjax(statusEnum.success,  _('停用使用者成功'), user_arr).returnJSON()
        else:
            info(request ,'%s active user error' % request.user.username)
            return ResponseAjax(statusEnum.error,  _('請選擇停用或啟用')).returnJSON()
    else:
        info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
        return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()


@login_required
@permission_required('omuser.OmGroup_Add','/api/permission/denied/')
@try_except
def addGroupAjax(request):
    '''
    add group
    input: request
    return: json
    author: Kolin Hsu
    '''
    #function variable
    p_group = None
    #get postdata
    postdata = request.POST
    group_name = postdata.get('group_name','')
    parent_group_id = postdata.get('p_id','')
    functional_flag = strtobool(postdata.get('functional_flag_%B','False'))
    description = postdata.get('description','')
    #Server Side Rule Check
    require_field = ['group_name','functional_flag_%B']
    checker = DataChecker(postdata, require_field)
    if checker.get('status') == 'success':
        if parent_group_id:
            try:
                p_group = OmGroup.objects.get(id=parent_group_id)
            except:
                info(request ,'%s add group error' % request.user.username)
                return ResponseAjax(statusEnum.no_permission , _('父群組名稱錯誤')).returnJSON()
        if group_name:
            OmGroup.objects.create(name=group_name,display_name=group_name,parent_group=p_group,functional_flag=functional_flag,description=description)
            info(request ,'%s add group success' % request.user.username)
            return ResponseAjax(statusEnum.success, _('建立群組成功')).returnJSON()
        else:
            info(request ,'%s add group error' % request.user.username)
            return ResponseAjax(statusEnum.no_permission, _('群組名稱不得為空')).returnJSON()
    else:
        info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
        return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()


@login_required
@permission_required('omuser.OmGroup_Delete','/api/permission/denied/')
@try_except
def deleteGroupAjax(request):
    '''
    delete group
    input: request
    return: json
    author: Kolin Hsu
    '''
    postdata = request.POST
    group_name_list = postdata.getlist('group_name[]','')
    #Server Side Rule Check
    require_field = ['group_name[]']
    checker = DataChecker(postdata, require_field)
    if checker.get('status') == 'success':
        OmGroup.objects.filter(name__in=group_name_list,ad_flag=False).delete()
        info(request ,'%s delete group success' % request.user.username)
        return ResponseAjax(statusEnum.success , _('刪除成功')).returnJSON()
    else:
        info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
        return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()


@login_required
@permission_required('omuser.OmGroup_View','/api/permission/denied/')
@try_except
def groupUserAjax(request):
    '''
    add a user into groups or remove a user from groups
    input: request
    return: json
    author: Kolin Hsu
    '''
    #get postdata
    postdata = request.POST
    group_list = postdata.getlist('group_list[]','')
    username = postdata.get('username','')
    functional_flag = strtobool(postdata.get('functional_flag_%B','False'))
    #Server Side Rule Check
    require_field = ['username', 'functional_flag_%B']
    checker = DataChecker(postdata, require_field)
    if checker.get('status') == 'success':
        try:
            user = OmUser.objects.get(username=username)
        except Exception as e:
            error(request,e)
            return ResponseAjax(statusEnum.no_permission ,  _('使用者錯誤')).returnJSON()
        user_group_list = list(user.groups.filter(omgroup__functional_flag=functional_flag,omgroup__ad_flag=False).values_list('name',flat=True))
        if set(group_list) == set(user_group_list):
            pass
        else:
            delete_list = list(set(user_group_list) - set(group_list))
            add_list = list(set(group_list) - set(user_group_list))
            if delete_list:
                d_group = Group.objects.filter(name__in=delete_list)
                user.groups.remove(*d_group)
            if add_list:
                a_group = Group.objects.filter(name__in=add_list)
                user.groups.add(*a_group)
        info(request ,'%s add an user to groups success' % request.user.username)
        return ResponseAjax(statusEnum.success , _('更新成功')).returnJSON()
    else:
        info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
        return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()


@login_required
@permission_required('omuser.OmGroup_View','/page/403/')
def roleManagementPage(request):
    '''
    show role management page
    input: request
    return: role management page
    author: Kolin Hsu
    '''
    return render(request,'role_manage.html')


@login_required
@try_except
def listGroupAjax(request):
    '''
    show all role list
    input: request
    return: role object
    author: Kolin Hsu
    '''
    #get postdata
    postdata = request.POST
    functional_flag = postdata.get('functional_flag',False)
    ad_flag = postdata.getlist('ad_flag[]',['1','0'])
    datatable = postdata.get('datatable',False)
    #function variable
    if datatable:
        filed_list=['name__icontains','description__icontains']
        group_query = OmGroup.objects.filter(functional_flag=functional_flag,ad_flag__in=ad_flag).values('id','display_name','description')
        result = DatatableBuilder(request, group_query, filed_list)
        info(request ,'%s list group success' % request.user.username)
        return JsonResponse(result)
    else:
        group_list = list(OmGroup.objects.filter(functional_flag=functional_flag,ad_flag__in=ad_flag).values('id','group_uuid','display_name','parent_group','description').order_by('parent_group', '-id'))
        group_list = DataFormat(group_list)
        info(request ,'%s list group success' % request.user.username)
        return ResponseAjax(statusEnum.success, _('讀取成功'), group_list).returnJSON()


@login_required
@permission_required('omuser.OmGroup_View','/page/403/')
def roleDetailPage(request, role_id):
    '''
    show user profile page
    input:request
    return: profile page
    author: Kolin Hsu
    '''
    return render(request, "role_detail.html", locals())


@login_required
@permission_required('omuser.OmGroup_View','/api/permission/denied/')    
@try_except
def loadGroupAjax(request):
    '''
    show role data
    input: request
    return: json
    author: Kolin Hsu
    '''
    #function variable
    group_id = request.POST.get('group_id', '')
    result = {}
    role_permission_list=[]
    #Server Side Rule Check
    require_field = ['group_id']
    postdata = request.POST
    checker = DataChecker(postdata, require_field)
    #get postdata
    functional_flag = strtobool(postdata.get('functional_flag_%B','Flase'))
    ad_flag = strtobool(postdata.get('ad_flag_%B','False'))
    if checker.get('status') == 'success':
        group_obj = OmGroup.objects.get(id=group_id)
        all_user_list = list(OmUser.objects.all().values('username','nick_name','company','is_active'))
        group_user_list = list(group_obj.user_set.all().values_list('username',flat=True))
        #role data
        if functional_flag:
            all_permission_list = list(Permission.objects.filter(codename__icontains='Om').values('id','codename','name'))
            role_now = model_to_dict(group_obj)
            for per in role_now['permissions']:
                role_permission_list.append(per.codename)
            result['group'] = group_obj.display_name
            result['all_user_list'] = all_user_list
            result['all_permission_list'] = all_permission_list
            result['role_permission_list'] = role_permission_list
        else:
            result['group'] = group_obj.display_name
            result['all_user_list'] = all_user_list
        #common data
        result['description'] = group_obj.description
        result['group_user_list'] = group_user_list
        info(request ,'%s load group success' % request.user.username)
        return ResponseAjax(statusEnum.success, _('讀取成功'), result).returnJSON()
    else:
        info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
        return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()


@login_required
@try_except
def updateGroupAjax(request):
    '''
    update group data
    input: request
    return: json
    author: Kolin Hsu
    '''
    #function variable
    group_id = request.POST.get('group_id', '')
    #Server Side Rule Check
    require_field = ['group_id']
    postdata = request.POST
    checker = DataChecker(postdata, require_field)
    #get postdata
    name = postdata.get('name','')
    description = postdata.get('description','')
    if checker.get('status') == 'success':
        try:
            group_obj = OmGroup.objects.get(id=group_id)
            if name:
                if group_obj.functional_flag:
                    group_obj.name = name
                    group_obj.display_name = name
                else:
                    group_obj.display_name = name
            if description:
                group_obj.description = description
            group_obj.save()
            info(request ,'%s update group success' % request.user.username)
            return ResponseAjax(statusEnum.success, _('更新成功')).returnJSON()
        except:
            info(request ,'%s update group error' % request.user.username)
            return ResponseAjax(statusEnum.not_found, _('更新失敗')).returnJSON()
    else:
        info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
        return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()


@login_required
@permission_required('omuser.OmGroup_View','/api/permission/denied/')    
@try_except
def groupUsersAjax(request):
    '''
    add users into a group or removes users from a group
    input: request
    return: json
    author: Kolin Hsu
    '''
    postdata = request.POST
    user_list = postdata.getlist('user_list[]',[])
    group_id = postdata.get('group_id','')
    try:
        group = OmGroup.objects.get(id=group_id)
    except:
        return ResponseAjax(statusEnum.no_permission ,  _('組織錯誤')).returnJSON()
    #Server Side Rule Check
    require_field = ['group_id']
    checker = DataChecker(postdata, require_field)
    if checker.get('status') == 'success':
        group_user_list = list(group.user_set.all().values_list('username',flat=True))
        if set(user_list) == set(group_user_list):
            pass
        else:
            delete_list = list(set(group_user_list) - set(user_list))
            add_list = list(set(user_list) - set(group_user_list))
            if delete_list:
                d_users = OmUser.objects.filter(username__in=delete_list)
                group.user_set.remove(*d_users)
            if add_list:
                a_users = OmUser.objects.filter(username__in=add_list)
                group.user_set.add(*a_users)
        info(request ,'%s add users to group success' % request.user.username)
        return ResponseAjax(statusEnum.success , _('更新成功')).returnJSON()
    else:
        info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
        return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()


@login_required
@permission_required('omuser.OmGroup_View','/api/permission/denied/')    
@try_except
def rolePermissionAjax(request):
    '''
    add permissions into a group or removes permissions from a group
    input: request
    return: json
    author: Kolin Hsu
    '''
    postdata = request.POST
    per_list = postdata.getlist('per_list[]',[])
    group_id = postdata.get('group_id','')
    #Server Side Rule Check
    require_field = ['group_id']
    checker = DataChecker(postdata, require_field)
    if checker.get('status') == 'success':
        try:
            group = OmGroup.objects.get(id=group_id)
        except:
            return ResponseAjax(statusEnum.no_permission ,  _('角色錯誤')).returnJSON()
        group_per_list = list(group.permissions.all().values_list('codename',flat=True))
        if set(per_list) == set(group_per_list):
            pass
        else:
            delete_list = list(set(group_per_list) - set(per_list))
            add_list = list(set(per_list) - set(group_per_list))
            if delete_list:
                d_pers = Permission.objects.filter(codename__in=delete_list)
                group.permissions.remove(*d_pers)
            if add_list:
                a_pers = Permission.objects.filter(codename__in=add_list)
                group.permissions.add(*a_pers)
        info(request ,'%s add permissions to group success' % request.user.username)
        return ResponseAjax(statusEnum.success , _('更新成功')).returnJSON()
    else:
        info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
        return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()


def addPermissionToRole(role_name, per_list):
    '''
    add permission to role
    '''
    try:
        group = OmGroup.objects.get_or_create(name=role_name,display_name=role_name,functional_flag=True)[0]
        group_per_list = list(group.permissions.all().values_list('codename',flat=True))
        add_list = list(set(per_list) - set(group_per_list))
        if add_list:
            a_pers = Permission.objects.filter(codename__in=add_list)
            group.permissions.add(*a_pers)
        return True
    except Exception as e:
        debug('add permission to role error: ' % e.__str__())
        return False



@login_required
def changePasswodPage(request):
    '''
    change password page
    input:request
    return: html
    author: Kolin Hsu
    '''
    return render(request, "change_password.html")


@login_required
@try_except
def changePasswordAjax(request):
    '''
    change password
    input:request
    return: json
    author: Kolin Hsu
    '''
    this_user = request.user
    postdata = request.POST
    input_old = postdata.get('org_token')
    input_new = postdata.get('token')
    input_new1 = postdata.get('token2')
    #Server Side Rule Check
    require_field = ['org_token', 'token', 'token2']
    checker = DataChecker(postdata, require_field)
    if checker.get('status') == 'success':
        user_auth = authenticate(username=this_user, password=input_old)
        
        if user_auth is not None:
            if input_new == input_new1:
                this_user.set_password(input_new)
                this_user.save()
                info(request ,'%s change password success' % request.user.username)
                return ResponseAjax(statusEnum.success , _('密碼修改成功')).returnJSON()
            else:
                info(request ,'%s change password error' % request.user.username)
                return ResponseAjax(statusEnum.no_permission , _('請輸入相同密碼')).returnJSON()
        else:
            info(request ,'%s change password error' % request.user.username)
            return ResponseAjax(statusEnum.no_permission , _('舊密碼輸入錯誤')).returnJSON()
    else:
        info(request ,'%s missing some require variable or the variable type error.' % request.user.username)
        return ResponseAjax(statusEnum.not_found, checker.get('message'), checker).returnJSON()


@csrf_exempt
def getSecurityAjax(request):
    '''
    api get security
    input: request.headers['Authorization']
    return: json
    author: Kolin Hsu
    ''' 
    #get request headers
    basic_auth_str = request.headers['Authorization'][6:]
    username, password = base64.b64decode(basic_auth_str).decode('utf-8').split(':')
    #Server Side Rule Check
    if checkEmailFormat(username):
        usersearch = OmUser.objects.get(email=username)
        user = auth.authenticate(username=usersearch.username, password=password)
    else:
        username_db = OmUser.objects.get(username__icontains=username).username
        user = auth.authenticate(username=username_db, password=password)
       
    if user is not None and user.is_active:
        #check user already has security token or not
        global_userObj = GlobalObject.__userObj__.get(username_db)
        if global_userObj is not None:
            expired_datetime = global_userObj['updatetime'] + timedelta(minutes=5)
            if datetime.now() < expired_datetime:
                #update security token date-time
                security = global_userObj['security']
                GlobalObject.__securityObj__[security]['updatetime'] = datetime.now()
            else:
                #remove expired security token and create a new security token
                security_old = global_userObj['security']
                GlobalObject.__securityObj__.pop(security_old, None)
                new_uuid = uuid.uuid4()
                security = str(new_uuid)
                GlobalObject.__securityObj__[security] = {"username":username_db,"security":security,"updatetime":datetime.now()}
        else:
            #create a new security token
            new_uuid = uuid.uuid4()
            security = str(new_uuid)
            GlobalObject.__securityObj__[security] = {"username":username_db,"security":security,"updatetime":datetime.now()}
            
        GlobalObject.__userObj__[username_db] = GlobalObject.__securityObj__[security]
        tokenObj = {}
        tokenObj['security'] = security
        info(request ,'%s api get security success' % request.user.username)
        return ResponseAjax(statusEnum.success,  _('取得成功'), tokenObj).returnJSON()
    else:
        info(request ,'%s api get security error' % request.user.username)
        return ResponseAjax(statusEnum.no_permission ,  _('使用者不存在或未啟用。')).returnJSON()
    

@login_required
@permission_required('omuser.OmGroup_View','/page/403/')
def groupManagementPage(request):
    '''
    show group management page
    input: request
    return: group management page
    author: Kolin Hsu
    '''
    return render(request,'group_manage.html')


@login_required
@permission_required('omuser.OmGroup_View','/page/403/')
def groupDetailPage(request, group_id):
    '''
    show group detail page
    input:request
    return: group detail page
    author: Kolin Hsu
    '''
    return render(request, "group_detail.html", locals())


@login_required
@permission_required('omuser.OmGroup_View','/page/403/')
def adGroupPage(request):
    '''
    show AD page
    input: request
    return: AD page
    author: Kolin Hsu
    '''
    if check_ldap_app():
        return render(request,'adgroup_list.html')
    else:
        return render(request,'home.html')

@login_required
@permission_required('omuser.OmGroup_View','/page/403/')
def adGroupDetailPage(request, group_id):
    '''
    show group detail page
    input:request
    return: group detail page
    author: Kolin Hsu
    '''
    if check_ldap_app():
        return render(request, "adgroup_detail.html", locals())
    else:
        return render(request,'home.html')


def getAgreeAjax(request):
    '''
    load agree detial
    input:request
    return: agree detail
    author: pei lin
    '''
    agree_type = request.POST.get('agree_type', '')
    agree_detail = SystemSetting.objects.get(name=agree_type).value
    return ResponseAjax(statusEnum.success,  _('取得成功'), agree_detail).returnJSON()