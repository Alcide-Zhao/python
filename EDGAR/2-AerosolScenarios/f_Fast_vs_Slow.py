"""
This is to plot the TS  from the EDGAR six experiments
data inputs are forty years of monthly TS
	first step is to process the monthly TS into monthly mean
	second step is to process annual mean of monthly mean
"""
import site
import os
import numpy as np
import netCDF4 as nc4
from scipy import stats
import scipy.io as sio
import math
import matplotlib.pyplot as plt
from scipy.interpolate import interp2d  as interp2d
from scipy.stats import mannwhitneyu as man_test
from scipy.stats import ttest_ind as student_test

lib_path = os.path.join(
    os.path.realpath(
        os.path.dirname(__file__)
    ), 
    os.path.pardir,os.path.pardir,
)
site.addsitedir(lib_path)
from lib import *
def AreaWeight(lon1,lon2,lat1,lat2):
	'''
	calculate the earth radius in m2
	'''
	radius = 6371000;
	area = (math.pi/180)*np.power(radius,2)*np.abs(lon1-lon2)*\
	(np.abs(np.sin(np.radians(lat1))-np.sin(np.radians(lat2))))
	# print np.nansum(np.nansum(area,axis=1),axis=0)
	return area
	
def box_clip(lon_s,lon_e,lat_s,lat_e,lon,lat,mask):
	"""
	fill the range outside the box with 0
	"""
	lon = np.array(lon)
	lat = np.array(lat)
	colum_s = [index for index in range(len(lon)) if np.abs(lon-lon_s)[index] == np.min(np.abs(lon-lon_s))][0]
	colum_e = [index for index in range(len(lon)) if np.abs(lon-lon_e)[index] == np.min(np.abs(lon-lon_e))][0]
	row_s = [index for index in range(len(lat)) if np.abs(lat-lat_s)[index] == np.min(np.abs(lat-lat_s))][0]
	row_e = [index for index in range(len(lat)) if np.abs(lat-lat_e)[index] == np.min(np.abs(lat-lat_e))][0]
	if (colum_s> colum_e):
		cache = colum_e; colum_e = colum_s; colum_s = cache;
	if (row_s> row_e):
		cache = row_e; row_e = row_s; row_s = cache;
	mask[:,:colum_s] =0; mask[:,colum_e:] =0
	mask[:row_s,:] =0; mask[row_e:,:] =0
	return mask

def mask_weight(region_key,lon,lat,reverse=False):
	"""
	Read in the country mask
	interpolate it to the required resolution grids with lon_interp,lat_interp 
	
	"""
	lon_res = lon[1] - lon[0];lat_res = lat[1] - lat[0];
	lons,lats = np.meshgrid(lon,lat)
	area = AreaWeight(lons,lons+lon_res,lats,lats+lat_res)

	##OCEAN_MASKS FOR COUNTRIES
	ocean_mask = sio.loadmat('/home/s1667168/coding/python/external_data/Euro_USA_AUS_BRICS_STA_720_360.mat')
	lon_mask = ocean_mask['lon'][0,:];
	lat_mask = ocean_mask['lat'][0,:];
	box_region_dic={'All':[0,360,-90,90],'ASIA':[65,145,5,45],'US':[240,290,30,50],'ARCTIC':[0,360,60,90],'TROPICS':[0,360,-28,28],'EUROPE':[0,40,30,70],}
	if (region_key == 'USA' or region_key == 'Europe' or region_key == 'India' or region_key == 'China' or region_key == 'GloLand'):
		mask= ocean_mask[region_key][:]
	elif  region_key in box_region_dic:
		mask= ocean_mask['All'][:]
		box = box_region_dic[region_key]
		mask = box_clip(box[0],box[1],box[2],box[3],lon_mask,lat_mask,mask)
	else:
		print "error region name"
	
	# interpolate from 360*720 to 192*288
	mask[np.isnan(mask)]=0;	mask[mask>0]=1;
	f = interp2d(lon_mask, lat_mask, mask,kind='linear'); mask = f(lon, lat);
	# plt.imshow(mask,origin='lower');plt.show()
	mask[mask >= 1] = 1;mask[mask < 1] = 0;
	# weight each grid cell by its area weight against the total area
	if reverse:
		mask=1-mask
	mask[mask==0] = np.nan
	mask=np.multiply(mask,area); 
	mask_weighted = np.divide(mask,np.nansum(np.nansum(mask,axis=1),axis=0))
	return mask	

def spatial_figure(axs,data,p_value,lons,lats,colormap,colorbar_min,colorbar_max,tb_lef=True,tb_bot=True): #c_bad,c_under,c_over,c_number=20,
	"""
	input : all parameters and data rel;ated to the figure you want to plot_title
	output : a spatial map of the data
	"""
	# plt.imshow(p_value);plt.show()
	lons[lons>180]-=360; 
	# calculate the origin of the map
	lon_0 = lons.mean(); 
	lat_0 = lats.mean(); 
	
	lon_b = np.min(lons); lon_e = np.max(lons)
	lat_b = np.min(lats); lat_e = np.max(lats)	
	lon_bin = 60; lat_bin = 30
	map = Basemap(lat_0=0, lon_0=0,llcrnrlon=lon_b,llcrnrlat=lat_b,urcrnrlon=lon_e,urcrnrlat=lat_e,ax=axs,projection='cyl')
	lon, lat = np.meshgrid(lons, lats)
	xi, yi = map(lon, lat)
	# s = map.pcolor(xi, yi, data)
	
	if tb_lef:
		map.drawparallels(np.arange(round(lat_b,0)-lat_bin, round(lat_e,0)+lat_bin, lat_bin), labels=[1,0,0,0],linewidth=0.0,fontsize=8)
	if tb_bot:
		map.drawmeridians(np.arange(round(lon_b,0), round(lon_e,0)+lon_bin, lon_bin), labels=[0,0,0,1],linewidth=0.0,fontsize=8)
	# Add Coastlines, States, and Country Boundaries
	map.drawcoastlines(); #map.drawcountries() #map.drawstates(); #
	masked_obj = np.ma.masked_where(np.isnan(data), data)
	# masked_obj = maskoceans(lon,lat,masked_obj)
	cmap = discrete_cmap(10,colormap)
	cmap.set_bad([1,1,1],alpha = 1.0); #cmap.set_over('k'); cmap.set_under('darkblue');
	colormesh = map.pcolormesh(xi, yi, masked_obj,cmap=cmap,vmin=colorbar_min, vmax=colorbar_max,latlon=True)
	pm = np.ma.masked_not_equal(p_value, 1)
	map.pcolor(xi, yi, np.multiply(pm,masked_obj), hatch='+', alpha=0.,lw=0.9,latlon=True)
	return colormesh
		
def data_readin(variable,exp):	
	def day2datetime(scenario,days):
		"""
		# convert days from a reference into int datetime 
		# do not take leap years into account
		"""
		date_int = np.empty((len(days)));date_int[:]=np.nan
		if scenario.startswith('F_'):
			start_year =2000
		elif scenario =='T1970C': 
			start_year =1970
		else: 
			start_year =2010
		start =(start_year*365)
		ith=0	
		for iday in days:
			month_days =np.array([31,28,31,30,31,30,31,31,30,31,30,31])
			calendar_days = np.array([0,31,59,90,120,151,181,212,243,273,304,334,365])
			total_days = int(iday) + start; 
			year = total_days//365; 
			remainder =  total_days%365
			if remainder ==0: year=year-1;month=12;day=31
			else: 
				month = 1+[layer for layer in range(len(calendar_days)) if calendar_days[layer]< remainder and calendar_days[layer+1]>=remainder][0]
				day = int(remainder - calendar_days[month-1])
				if day == 0: day = month_days[month-1]
			date_int[ith] = year*10000+month*100+day
			ith=ith+1
		return date_int.astype(int)


	def mon_mean2annual_mean(scenario,time,data):
		annual_mean=np.empty((30,192,288));annual_mean[:]=np.nan
		calendar_day = np.array([31,28,31,30,31,30,31,31,30,31,30,31])
		if scenario.startswith('F_'):
			year_series = range(2000,2030)
		elif scenario=='T1970RCP':
			year_series = range(2020,2050)
		elif scenario=='EdgEne':
			year_series = range(2200,2230)
		elif scenario=='Edg70GO':
			year_series = range(2070,2100)
		else:
			year_series = range(2130,2160)
		for iyear in year_series:
			# print scenario, iyear
			if (iyear == year_series[0] and time[0]//100 >= year_series[0] *100+1):
				layer_b=0
			else:
				layer_b = [layer for layer in range(len(time)) if time[layer]//100 == iyear*100+1][0]  #June01
			if (iyear == year_series[-1] and time[-1]//100 <= year_series[-1] *100+12):
				layer_e=-2
			else:
				layer_e = [layer for layer in range(len(time)) if time[layer]//100  == iyear*100+12][0]  #August 31
			data_cache = data[layer_b:layer_e+1,:,:]
			annual_mean[iyear-year_series[0],:,:] = stats.nanmean(data_cache,axis=0)
		return annual_mean

	def data_netcdf(exp,scenario,variable,region_key='All'):
		input_path ='/exports/csce/datastore/geos/users/s1667168/CESM_EDGAR/ModelOutput/'+exp+'/'
		if variable == 'precip':
			var_path = input_path+scenario+'/mon/atm/'+scenario+'.atm.mon.PRECC.nc'
			nc_fid = nc4.Dataset(var_path,mode='r')
			lat = nc_fid.variables['lat'][:]
			lon = nc_fid.variables['lon'][:]
			days = nc_fid.variables['time'][:]; time = day2datetime(scenario,days);#print time
			PRECC = (nc_fid.variables['PRECC'][:])*24*60*60*1000
			nc_fid.close()
			var_path = input_path+scenario+'/mon/atm/'+scenario+'.atm.mon.PRECL.nc'
			nc_fid = nc4.Dataset(var_path,mode='r')
			days = nc_fid.variables['time'][:]; time = day2datetime(scenario,days);#print time
			PRECL = (nc_fid.variables['PRECL'][:])*24*60*60*1000			
			nc_fid.close()
			data = PRECC+PRECL
		else:
			var_path = input_path+scenario+'/mon/atm/'+scenario+'.atm.mon.'+variable+'.nc'
			# print var_path
			nc_fid = nc4.Dataset(var_path,mode='r')
			lat = nc_fid.variables['lat'][:]
			lon = nc_fid.variables['lon'][:]
			days = nc_fid.variables['time'][:]; time = day2datetime(scenario,days);#print time
			data = nc_fid.variables[variable][:]
			nc_fid.close()
		if variable == "TS": data=data-273.15
		elif variable == 'CLDTOT':data=data*100
		elif variable == 'TGCLDLWP':data=data*10**(3)
		var40map = mon_mean2annual_mean(scenario,time,data)
		return lon,lat,var40map

		
	if exp=='CamOnly':
		lon,lat,Edg70GO = data_netcdf(exp,'F_Edg70GO',variable);
		_,_,Ref1970 = data_netcdf(exp,'F_1970',variable);
		_,_,EdgRef = data_netcdf(exp,'F_EdgRef',variable);
		_,_,EdgEne = data_netcdf(exp,'F_EdgEne',variable);
		_,_,EdgTech = data_netcdf(exp,'F_EdgTech',variable);
	elif exp=='FullCp':
		lon,lat,Edg70GO = data_netcdf(exp,'Edg70GO',variable)
		_,_,Ref1970 = data_netcdf(exp,'T1970RCP',variable)
		_,_,EdgRef = data_netcdf(exp,'EdgRef',variable)
		_,_,EdgEne = data_netcdf(exp,'EdgEne',variable)
		_,_,EdgTech = data_netcdf(exp,'EdgTech',variable)
	return lon,lat,Ref1970,Edg70GO,EdgEne,EdgRef,EdgTech
	
def spa_pat_reg_mean(variable):
	"""
	option: SpaPat or RegMean
	This function block is to produce a weighted_mask for specific regions (either administrative or box)
	and then produce the spatial mean (weighted)
	"""

	def mannwhitneyu_test(vairable1,variable2,p_threshold):
		# p_threshold=0.10
		size = np.array([np.shape(variable2)[1],np.shape(variable2)[2]]); 
		p_value = np.empty((size[0],size[1]));p_value[:]=np.nan
		# from scipy.stats import ttest_ind as test
		for x in range(size[0]):
			for y in range(size[1]):
				cache1 = vairable1[:,x,y]
				cache2 = variable2[:,x,y]
				if (cache2==cache1).all(): p_value[x,y] = np.nan
				else: _,p_value[x,y] = man_test(cache1,cache2);
		p_value[p_value>p_threshold]=np.nan;p_value[p_value<=p_threshold]=1
		return p_value
	####calculate the difference and their significance

	def decompose_forcings(Ref970,Edg70GO,EdgEne,EdgRef,EdgTech):
		def diff_sig(vairable1,variable2):
			dif = np.nanmean(vairable1,axis=0)-np.nanmean(variable2,axis=0)
			sig = mannwhitneyu_test(vairable1, variable2,p_threshold=0.1)
			# sig_dif = np.multiply(dif,sig)
			return dif,sig
		BEoA,BEoA_s = diff_sig(Edg70GO,Ref970)
		Ene,Ene_s = diff_sig(EdgRef,EdgEne)
		Tech,Tech_s = diff_sig(EdgRef,EdgTech)
		return np.stack((BEoA,Ene,Tech,BEoA_s,Ene_s,Tech_s),axis=0)

	lon,lat,Ref970_T,Edg70GO_T,EdgEne_T,EdgRef_T,EdgTech_T = data_readin(variable,exp='FullCp');    # fully coupled total response
	lon,lat,Ref970_F,Edg70GO_F,EdgEne_F,EdgRef_F,EdgTech_F = data_readin(variable,exp='CamOnly');    # local response as the dynamics are fixed
	Ref970_d = Ref970_T - Ref970_F;
	EdgEne_d = EdgEne_T - EdgEne_F;
	Edg70GO_d = Edg70GO_T - Edg70GO_F;
	EdgRef_d = EdgRef_T - EdgRef_F;
	EdgTech_d = EdgTech_T - EdgTech_F;
	fullCp = decompose_forcings(Ref970_T,Edg70GO_T,EdgEne_T,EdgRef_T,EdgTech_T)
	Fcomp = decompose_forcings(Ref970_F,Edg70GO_F,EdgEne_F,EdgRef_F,EdgTech_F)
	Dcomp = decompose_forcings(Ref970_d,Edg70GO_d,EdgEne_d,EdgRef_d,EdgTech_d)
	return lon,lat,fullCp,Fcomp,Dcomp


def plot_zonal_mean_uncertainty(ax,x1,x2,x3,y,xlim):
	ax.tick_params(axis='both', which='major', direction = 'in',left=True,right=True,bottom=True,top=True, pad=5)
	ax.axvline(x=0,color='k',linewidth = 1);ax.axhline(y=0,color='k',linewidth = 1);
	ax.set_ylim([-90,90]);ax.set_yticks(np.arange(-90,91,30));ax.set_yticklabels(('90S','60S','30S','EQ','30N','60N','90N'));
	ax.set_xlim([-xlim,xlim]);ax.set_xticks(np.arange(-xlim,xlim+.0000001,xlim/1.0))
	ax.plot(x1,y,'-',color="k",linewidth=2)
	ax.plot(x2,y,'-',color="b",linewidth=0.5)
	ax.plot(x3,y,'-',color="r",linewidth=0.5)
	ax.yaxis.tick_right()
	return ax


var = 'CLDTOT';lon,lat,fullCp,Fcomp,Dcomp = spa_pat_reg_mean(var)


if var =='CLDTOT':
	colorbar_min=-4;colorbar_max=4;colormap='RdBu_r';xlim=2 
elif var =='TGCLDLWP':
	 colorbar_min=-10;colorbar_max=10;colormap='RdBu_r';xlim=5 
elif var == 'precip':
	colorbar_min=-0.4;colorbar_max=0.4;colormap='BrBG';xlim=0.2
elif var =='ACTREL':	  #F CDNUMC ACTREL TGCLDLWP CLDTOT
	colorbar_min=-0.20;colorbar_max=0.20;xlim=0.10; colormap='RdBu_r';
elif var =='CDNUMC':	  #F CDNUMC ACTREL TGCLDLWP CLDTOT
	colorbar_min=-5;colorbar_max=5;xlim=4; colormap='RdBu_r';
else:
	print 'confirm the variable name'
	
fig = plt.figure(facecolor='White',figsize=[15,8.00]);pad= 5;
ax = plt.subplot2grid((3, 10), (0, 0), colspan=3)
ax.annotate('Best\nEstimation',xy=(-0.1,0.5), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='center', va='center',rotation='vertical',fontsize=15)	
ax.annotate('(a)',xy=(0.02,1.01), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)	
ax.annotate('Total',xy=(0.5,1.1), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='center', va='baseline',rotation='horizontal',fontsize=15)			
colormesh0 = spatial_figure(ax,fullCp[0,:,:],fullCp[3,:,:],lon,lat,colormap,colorbar_min,colorbar_max,tb_lef=False,tb_bot=False)


ax = plt.subplot2grid((3, 10), (0, 3), colspan=3)
ax.annotate('Fast',xy=(0.5,1.1), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='center', va='baseline',rotation='horizontal',color='b',fontsize=15)	
ax.annotate('(b)',xy=(0.02,1.01), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)					
spatial_figure(ax,Fcomp[0,:,:],Fcomp[3,:,:],lon,lat,colormap,colorbar_min,colorbar_max,tb_lef=False,tb_bot=False)

ax = plt.subplot2grid((3, 10), (0, 6), colspan=3)
ax.annotate('Slow',xy=(0.5,1.1), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='center', va='baseline',rotation='horizontal',color='r',fontsize=15)	
ax.annotate('(c)',xy=(0.02,1.01), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)		
colormesh1=spatial_figure(ax,Dcomp[0,:,:],Dcomp[3,:,:],lon,lat,colormap,colorbar_min,colorbar_max,tb_lef=False,tb_bot=False)

ax = plt.subplot2grid((3, 10), (0, 9), colspan=1)
ax.annotate('Zonal Mean',xy=(0.5,1.1), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='center', va='baseline',rotation='horizontal',fontsize=15)	
x1 = np.reshape(np.nanmean(fullCp[0,:,:],axis=1),192)
x2 = np.reshape(np.nanmean(Fcomp[0,:,:],axis=1),192)
x3 = np.reshape(np.nanmean(Dcomp[0,:,:],axis=1),192)
plot_zonal_mean_uncertainty(ax,x1,x2,x3,lat,xlim=xlim)


ax = plt.subplot2grid((3, 10), (1, 0), colspan=3)
ax.annotate('Energy\nConsumption',xy=(-0.1,0.5), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='center', va='center',rotation='vertical',fontsize=15)	
ax.annotate('(d)',xy=(0.02,1.01), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)			
colormesh0 = spatial_figure(ax,fullCp[1,:,:],fullCp[4,:,:],lon,lat,colormap,colorbar_min,colorbar_max,tb_lef=False,tb_bot=False)
ax = plt.subplot2grid((3, 10), (1, 3), colspan=3)
ax.annotate('(e)',xy=(0.02,1.01), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)					
colormesh0 = spatial_figure(ax,Fcomp[1,:,:],Fcomp[4,:,:],lon,lat,colormap,colorbar_min,colorbar_max,tb_lef=False,tb_bot=False)

ax = plt.subplot2grid((3, 10), (1, 6), colspan=3)
ax.annotate('(f)',xy=(0.02,1.01), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)		
colormesh0 = spatial_figure(ax,Dcomp[1,:,:],Dcomp[4,:,:],lon,lat,colormap,colorbar_min,colorbar_max,tb_lef=False,tb_bot=False)
ax = plt.subplot2grid((3, 10), (1, 9), colspan=1)

x1 = np.reshape(np.nanmean(fullCp[1,:,:],axis=1),192)
x2 = np.reshape(np.nanmean(Fcomp[1,:,:],axis=1),192)
x3 = np.reshape(np.nanmean(Dcomp[1,:,:],axis=1),192)
plot_zonal_mean_uncertainty(ax,x1,x2,x3,lat,xlim=xlim)

ax = plt.subplot2grid((3, 10), (2, 0), colspan=3)
ax.annotate('Technology\nAdvancements',xy=(-0.1,0.5), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='center', va='center',rotation='vertical',fontsize=15)	
ax.annotate('(g)',xy=(0.02,1.01), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)				
colormesh0 = spatial_figure(ax,fullCp[2,:,:],fullCp[5,:,:],lon,lat,colormap,colorbar_min,colorbar_max,tb_lef=False,tb_bot=False)

ax = plt.subplot2grid((3, 10), (2, 3), colspan=3)
ax.annotate('(h)',xy=(0.02,1.01), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)					
colormesh0 = spatial_figure(ax,Fcomp[2,:,:],Fcomp[5,:,:],lon,lat,colormap,colorbar_min,colorbar_max,tb_lef=False,tb_bot=False)

ax = plt.subplot2grid((3, 10), (2, 6), colspan=3)
ax.annotate('(i)',xy=(0.02,1.01), xytext=(0, pad),
                xycoords='axes fraction', textcoords='offset points',
                ha='left', va='baseline',rotation='horizontal',fontsize=15)		
colormesh0 = spatial_figure(ax,Dcomp[2,:,:],Dcomp[5,:,:],lon,lat,colormap,colorbar_min,colorbar_max,tb_lef=False,tb_bot=False)
ax = plt.subplot2grid((3, 10), (2, 9), colspan=1)
x1 = np.reshape(np.nanmean(fullCp[2,:,:],axis=1),192)
x2 = np.reshape(np.nanmean(Fcomp[2,:,:],axis=1),192)
x3 = np.reshape(np.nanmean(Dcomp[2,:,:],axis=1),192)
plot_zonal_mean_uncertainty(ax,x1,x2,x3,lat,xlim=xlim)



cbar_ax = fig.add_axes([0.18, 0.03, 0.64, 0.015])
char = fig.colorbar(colormesh1,orientation='horizontal',extend='both',cax=cbar_ax,ticks=np.round(np.arange(0,1.1,0.1)*(colorbar_max-colorbar_min)+colorbar_min,2))
if var == 'CLDTOT':
	cbar_ax.annotate('%',xy=(1.10,-1.1), xytext=(0, pad),
					xycoords='axes fraction', textcoords='offset points',
					ha='center', va='bottom',rotation='horizontal',fontsize=15)
elif var == 'TGCLDLWP':
	cbar_ax.annotate(r'$\mathrm{\mathsf{g\/m^{-2}}}$',xy=(1.10,-1.6), xytext=(0, pad),
					xycoords='axes fraction', textcoords='offset points',
					ha='center', va='bottom',rotation='horizontal',fontsize=15)
elif var == 'precip':
	cbar_ax.annotate(r'$\mathrm{\mathsf{mm\/day^{-1}}}$',xy=(1.10,-1.4), xytext=(0, pad),
					xycoords='axes fraction', textcoords='offset points',
					ha='center', va='bottom',rotation='horizontal',fontsize=15)
elif var == 'ACTREL':
	cbar_ax.annotate('micron',xy=(1.10,-1.4), xytext=(0, pad),
					xycoords='axes fraction', textcoords='offset points',
					ha='center', va='bottom',rotation='horizontal',fontsize=15)
elif var == 'CDNUMC':
	cbar_ax.annotate(r'($10^{9}$)',xy=(1.10,-1.4), xytext=(0, pad),
					xycoords='axes fraction', textcoords='offset points',
					ha='center', va='bottom',rotation='horizontal',fontsize=15)
plt.subplots_adjust(left=0.05, bottom=0.08, right=0.95, top=0.92, wspace=0.1, hspace=0.30); 
plt.savefig(var+'_Fast_vs_Slow.png', format='png', dpi=1000)