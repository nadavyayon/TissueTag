import numpy as np # last update 18/3/23
from bokeh.models import PolyDrawTool,PolyEditTool,FreehandDrawTool
from bokeh.plotting import figure, show
from PIL import Image
Image.MAX_IMAGE_PIXELS = None



def read_image(
    path,
    scale=1,
    scaleto1ppm=True,
    filterkernel=10,
    contrast_factor=1,
):
    """
        Read H&E image 
        
        Parameters
        ----------     
        path 
            path to image, must follow supported Pillow formats - https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html
        categorical_covariate_keys
        scale 
            a factor to scale down image, if this is applied (any value smaller than 1) a gaussian filter would be applied 
        filterkernel
            for scaling image and filtering before scalng by a factor, default = 10

    """
    from PIL import ImageFilter, ImageEnhance
    im = Image.open(path)
    
   
    if scale<1:
        width, height = im.size
        newsize = (int(width*scale), int(height*scale))
        # filtered = im.filter(ImageFilter.GaussianBlur(radius=filterkernel))
        im = im.resize(newsize)
    if scaleto1ppm:
        ppm = im.info['resolution'][0]
        width, height = im.size
        newsize = (int(width/ppm), int(height/ppm))
        # filtered = im.filter(ImageFilter.GaussianBlur(radius=filterkernel))
        im = im.resize(newsize)
    im = im.convert("RGBA")
    enhancer = ImageEnhance.Contrast(im)
    factor = contrast_factor #increase contrast
    im = enhancer.enhance(factor*factor)
    return np.array(im)


def scribbler(
    imarray,
    anno_dict,
    plot_scale,
):
    """
        interactive scribble line annotations with Bokeh  
        
        Parameters
        ----------     
        imarray  
            image in numpy array format (nparray)
        anno_dict
            dictionary of structures to annotate and colors for the structures     

    """

    imarray = imarray.astype('uint8')
    imarray_c = imarray[:,:].copy()
    np_img2d = imarray_c.view("uint32").reshape(imarray_c.shape[:2])

    p =  figure(width=int(imarray_c.shape[1]/3.5*plot_scale),height=int(imarray_c.shape[0]/3.5*plot_scale),match_aspect=True)
    plotted_image = p.image_rgba(image=[np_img2d], x=0, y=0, dw=imarray_c.shape[1], dh=imarray_c.shape[0])
    anno_color_map = anno_dict
    anno_color_map
    render_dict = {}
    draw_tool_dict = {}
    for l in list(anno_dict.keys()):
        render_dict[l] = p.multi_line([], [], line_width=5, alpha=0.4, color=anno_color_map[l])
        draw_tool_dict[l] = FreehandDrawTool(renderers=[render_dict[l]], num_objects=50)
        draw_tool_dict[l].description = l
        p.add_tools(draw_tool_dict[l])
    
    
    return p, render_dict
    
def complete_pixel_gaps(x,y):
    from scipy import interpolate
    newx1 = []
    newx2 = []
    for idx,px in enumerate(x[:-1]):
        f = interpolate.interp1d(x[idx:idx+2], y[idx:idx+2])
        gapx1 = np.linspace(x[idx],x[idx+1],num=np.abs(x[idx+1]-x[idx]+1))
        gapx2 = f(gapx1).astype(int)
        newx1 = newx1 + list(gapx1[:]) 
        newx2 = newx2 + list(gapx2[:]) 

    newy1 = []
    newy2 = []
    for idx,py in enumerate(y[:-1]):
        f = interpolate.interp1d(y[idx:idx+2], x[idx:idx+2])
        gapy1 = np.linspace(y[idx],y[idx+1],num=np.abs(y[idx+1]-y[idx]+1))
        gapy2 = f(gapy1).astype(int)
        newy1 = newy1 + list(gapy1[:]) 
        newy2 = newy2 + list(gapy2[:]) 
    newx = newx1 + newy2
    newy = newx2 + newy1


    return newx,newy


def scribble_to_labels(
    imarray,
    render_dict,
    line_width = 10,
):
    """
        extract scribbles to a label image 
        
        Parameters
        ----------     
        imarray  
            image in numpy array format (nparray) used to calculate the label image size
        render_dict
            Bokeh object carrying annotations 
        line_width
            width of the line labels (int)

    """
    
    annotations = {}
    training_labels = np.zeros((imarray.shape[1],imarray.shape[0]), dtype=np.uint8) # blank annotation image
    # annotations = pd.DataFrame()
    for idx,a in enumerate(render_dict.keys()):
        print(a)
        xs = []
        ys = []
        annotations[a] = []
        for o in range(len(render_dict[a].data_source.data['xs'])):
            xt,yt = complete_pixel_gaps(np.array(render_dict[a].data_source.data['xs'][o]).astype(int),np.array(render_dict[a].data_source.data['ys'][o]).astype(int))
            xs = xs + xt
            ys = ys + yt
            annotations[a] = annotations[a] + [np.vstack([np.array(render_dict[a].data_source.data['xs'][o]).astype(int),np.array(render_dict[a].data_source.data['ys'][o]).astype(int)])] # to save 

        training_labels[np.array(xs).astype(int),np.array(ys).astype(int)] = idx+1
        # df = pd.DataFrame(render_dict[a].data_source.data)
        # df.index = a+'-'+df.index.astype('str')
        # annotations = pd.concat([annotations,df])
    training_labels = training_labels.transpose()
    import skimage as sk 
    return sk.segmentation.expand_labels(training_labels, distance=10)


def rgb_from_labels(labelimage,colors):

    labelimage_rgb = np.zeros((labelimage.shape[0],labelimage.shape[1] ,4))
    from PIL import ImageColor
    for c in range(len(colors)):
        color = ImageColor.getcolor(colors[c], "RGB")
        labelimage_rgb[np.where(labelimage == c+1)[0],np.where(labelimage == c+1)[1],0:3] = np.array(color)
    labelimage_rgb[:,:,3] = 255
    return labelimage_rgb.astype('uint8')


def sk_rf_classifier(
    im,
    training_labels
    
):
    from skimage import data, segmentation, feature, future
    from sklearn.ensemble import RandomForestClassifier
    from functools import partial

    sigma_min = 1
    sigma_max = 16
    features_func = partial(feature.multiscale_basic_features,
                            intensity=True, edges=False, texture=~True,
                            sigma_min=sigma_min, sigma_max=sigma_max, channel_axis=-1)

    features = features_func(im)
    clf = RandomForestClassifier(n_estimators=50, n_jobs=-1,
                                 max_depth=10, max_samples=0.05)
    clf = future.fit_segmenter(training_labels, features, clf)
    return future.predict_segmenter(features, clf)


def overlay_lebels(im1,im2,alpha=0.8,show=True):
    #generate overlay image
    import matplotlib.pyplot as plt
    plt.rcParams["figure.figsize"] = [10, 10]
    plt.rcParams["figure.dpi"] = 100
    out_img = np.zeros(im1.shape,dtype=im1.dtype)
    out_img[:,:,:] = (alpha * im1[:,:,:]) + ((1-alpha) * im2[:,:,:])
    out_img[:,:,3] = 255
    if show:
        plt.imshow(out_img,origin='lower')
    return out_img


    
def annotator(
    imarray,
    annotation,
    anno_dict,
    fig_downsize_factor = 5,
    
):
    """
        interactive annotation tool with line annotations using Bokeh tabs for toggling between morphology and annotation. 
        The principle is that selecting closed/semiclosed shaped that will later be filled accordind to the proper annotation.
        
        Parameters
        ----------     
        imarray  
            image in numpy array format (nparray)
        annotation  
            label image in numpy array format (nparray)
        anno_dict
            dictionary of structures to annotate and colors for the structures             
        fig_downsize_factor
            a plotting thing

    """
    
    from bokeh.models import PolyDrawTool,PolyEditTool,FreehandDrawTool
    from bokeh.plotting import figure, show
    from bokeh.models import TabPanel, Tabs

    # tab1
    imarray_c = annotation[:,:].copy()
    np_img2d = imarray_c.view("uint32").reshape(imarray_c.shape[:2])
    # p = figure(width=int(imarray_c.shape[1]/fig_downsize_factor),height=int(imarray_c.shape[0]/fig_downsize_factor))
    p = figure(width=int(imarray_c.shape[1]/3.5),height=int(imarray_c.shape[0]/3.5),match_aspect=True)
    plotted_image = p.image_rgba(image=[np_img2d], x=0, y=0, dw=imarray_c.shape[1], dh=imarray_c.shape[0])
    tab1 = TabPanel(child=p, title="Annotation")

    # tab2
    imarray_c = imarray[:,:].copy()
    np_img2d = imarray_c.view("uint32").reshape(imarray_c.shape[:2])
    p1 = figure(width=int(imarray_c.shape[1]/3.5),height=int(imarray_c.shape[0]/3.5),match_aspect=True, x_range=p.x_range,y_range=p.y_range)
    plotted_image = p1.image_rgba(image=[np_img2d], x=0, y=0, dw=imarray_c.shape[1], dh=imarray_c.shape[0])
    tab2 = TabPanel(child=p1, title="Image")

    # # tab3
    # imarray_c = result_rgb[:,:].copy()
    # np_img2d = imarray_c.view("uint32").reshape(imarray_c.shape[:2])
    # p2 = figure(width=int(imarray_c.shape[1]/fig_downsize_factor),height=int(imarray_c.shape[0]/fig_downsize_factor), x_range=p.x_range,y_range=p.y_range)
    # plotted_image = p2.image_rgba(image=[np_img2d], x=0, y=0, dw=imarray_c.shape[1], dh=imarray_c.shape[0])
    # tab3 = TabPanel(child=p2, title="Annotation")
    anno_color_map = anno_dict
    anno_color_map

    # brushes
    render_dict = {}
    draw_tool_dict = {}
    for l in list(anno_dict.keys()):
        render_dict[l] = p.multi_line([], [], line_width=5, alpha=0.4, color=anno_color_map[l])
        draw_tool_dict[l] = FreehandDrawTool(renderers=[render_dict[l]], num_objects=50)
        draw_tool_dict[l].description = l
        p.add_tools(draw_tool_dict[l])

    tabs = Tabs(tabs=[tab1, tab2])
    return tabs, render_dict


def update_annotator(
    imarray,
    result,
    anno_dict,
    render_dict,
    alpha,
):
    """
        updates annotations and generates overly (out_img) and the label image (corrected_labels)
        
        Parameters
        ----------     
        imarray  
            image in numpy array format (nparray)
        result  
            label image in numpy array format (nparray)
        anno_dict
            dictionary of structures to annotate and colors for the structures     
        render_dict
            bokeh data container

    """
    
    from skimage.draw import polygon
    corrected_labels = result.copy()
    # annotations = pd.DataFrame()
    for idx,a in enumerate(render_dict.keys()):
        if render_dict[a].data_source.data['xs']:
            print(a)
            for o in range(len(render_dict[a].data_source.data['xs'])):
                x = np.array(render_dict[a].data_source.data['xs'][o]).astype(int)
                y = np.array(render_dict[a].data_source.data['ys'][o]).astype(int)
                rr, cc = polygon(y, x)
                inshape = np.where(np.array(result.shape[0]>rr) & np.array(0<rr) & np.array(result.shape[1]>cc) & np.array(0<cc))[0]
                corrected_labels[rr[inshape], cc[inshape]] = idx+1 
                # make sure pixels outside the image are ignored

    #generate overlay image
    rgb = rgb_from_labels(corrected_labels,list(anno_dict.values()))
    out_img = overlay_lebels(imarray,rgb,alpha=alpha,show=False)
    # out_img = out_img.transpose() 
    return out_img, corrected_labels


def rescale_image(
    label_image,
    target_size,
):
    """
        rescales label image to original image size 
        
        Parameters
        ----------     
        label_image  
            labeled image (nparray)
        scale  
            factor to enlarge image

    """
    imP = Image.fromarray(label_image)
    newsize = (target_size[0], target_size[1])
    
    return np.array(imP.resize(newsize))


def save_annotation(
    folder,
    label_image,
    file_name, 
    anno_names
):
    """
        saves the annotated image as .tif and in addition saves the translation from annotations to labels in a pickle file 
        
        Parameters
        ----------     
        label_image  
            labeled image (nparray)
        file_name  
            name for tif image and pickle

    """
    import pickle
    from PIL import Image 
    label_image = Image.fromarray(label_image)
    label_image.save(folder+file_name+'.tif')
    with open(folder+file_name+'.pickle', 'wb') as handle:
        pickle.dump(dict(zip(anno_names,range(1,len(anno_names)+1))), handle, protocol=pickle.HIGHEST_PROTOCOL)

def load_annotation(
    folder,
    label_image,
    file_name, 
):
    """
        saves the annotated image as .tif and in addition saves the translation from annotations to labels in a pickle file 
        
        Parameters
        ----------     
        label_image  
            labeled image (nparray)
        file_name  
            name for tif image and pickle

    """
    import pickle
    imP = Image.open(folder+file_name+'.tif')
    im = np.array(imP)
    with open(folder+file_name+'.pickle', 'rb') as handle:
        anno_order = pickle.load(handle)
    return im, anno_order
    
    

#The following notebook is a series of simple examples of applying the method to data on a 
#CODEX/Keyence microscrope to produce virtual H&E images using fluorescence data.  If you 
#find it useful, will you please consider citing the relevant article?:

#Creating virtual H&E images using samples imaged on a commercial CODEX platform
#Paul D. Simonson, Xiaobing Ren,  Jonathan R. Fromm
#doi: https://doi.org/10.1101/2021.02.05.21249150
#Submitted to Journal of Pathology Informatics, December 2020
def simonson_vHE(
    dapi_image,
    eosin_image,
):
    import matplotlib.image as mpimg
    def createVirtualHE(dapi_image, eosin_image, k1, k2, background, beta_DAPI, beta_eosin):
        new_image = np.empty([dapi_image.shape[0], dapi_image.shape[1], 4])
        new_image[:,:,0] = background[0] + (1 - background[0]) * np.exp(- k1 * beta_DAPI[0] * dapi_image - k2 * beta_eosin[0] * eosin_image)
        new_image[:,:,1] = background[1] + (1 - background[1]) * np.exp(- k1 * beta_DAPI[1] * dapi_image - k2 * beta_eosin[1] * eosin_image)
        new_image[:,:,2] = background[2] + (1 - background[2]) * np.exp(- k1 * beta_DAPI[2] * dapi_image - k2 * beta_eosin[2] * eosin_image)
        new_image[:,:,3] = 1
        new_image = new_image*255
        return new_image.astype('uint8')

    #Defaults:
    k1 = k2 = 0.001

    background_red = 0.25
    background_green = 0.25
    background_blue = 0.25
    background = [background_red, background_green, background_blue]

    beta_DAPI_red = 9.147
    beta_DAPI_green = 6.9215
    beta_DAPI_blue = 1.0
    beta_DAPI = [beta_DAPI_red, beta_DAPI_green, beta_DAPI_blue]

    beta_eosin_red = 0.1
    beta_eosin_green = 15.8
    beta_eosin_blue = 0.3
    beta_eosin = [beta_eosin_red, beta_eosin_green, beta_eosin_blue]


    dapi_image = dapi_image[:,:,0]+dapi_image[:,:,1]
    eosin_image = eosin_image[:,:,0]+eosin_image[:,:,1]

    print(dapi_image.shape)
    return createVirtualHE(dapi_image, eosin_image, k1, k2, background=background, beta_DAPI=beta_DAPI, beta_eosin=beta_eosin)